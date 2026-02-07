from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from inspect import isawaitable
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route

from apps.orchestrator.api.idempotency import IdempotencyStore, create_idempotency_store
from apps.orchestrator.api.serializers import (
    interrupt_to_dict,
    run_to_dict,
    workflow_summary_to_dict,
    workflow_to_dict,
    workflow_version_to_dict,
)
from apps.orchestrator.api.store import create_run_store
from apps.orchestrator.api.workflow_store import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    create_workflow_store,
)
from apps.orchestrator.executors import AGENTS_AVAILABLE, AgentExecutor, MockAgentExecutor
from apps.orchestrator.runtime import Edge, MultiWorkflowRuntimeService, Node, Workflow
from apps.orchestrator.runtime.env import get_env
from apps.orchestrator.runtime.models import Event as RuntimeEvent
from apps.orchestrator.streaming.sse import _event_stream
from apps.orchestrator.webhooks.service import WebhookService

_ROOT_DIR = Path(__file__).resolve().parents[3]
_OPENAPI_SPEC_PATH = _ROOT_DIR / "docs" / "api" / "openapi.yaml"
_API_REFERENCE_PATH = _ROOT_DIR / "docs" / "api" / "reference.md"
_WORKFLOW_AUTHORING_GUIDE_PATH = _ROOT_DIR / "docs" / "architecture" / "workflow-authoring-agents.md"
_WORKFLOW_DRAFT_SCHEMA_PATH = _ROOT_DIR / "docs" / "api" / "schemas" / "workflow-draft.schema.json"
_WORKFLOW_EXPORT_SCHEMA_PATH = _ROOT_DIR / "docs" / "api" / "schemas" / "workflow-export-v1.schema.json"


class ApiContext:
    def __init__(
        self,
        run_store: Optional[Any] = None,
        workflow_store=None,
        runtime: Optional[MultiWorkflowRuntimeService] = None,
        default_inbound_secret: Optional[str] = None,
        default_integration_key: str = "default",
    ) -> None:
        self.run_store = run_store
        self.workflow_store = workflow_store
        self.runtime = runtime
        self.idempotency: Optional[IdempotencyStore] = None
        self._workflow_store_owned = False
        self._run_store_owned = False
        self._idempotency_owned = False
        self._runtime_started = False
        self.webhooks = WebhookService.create()
        if default_inbound_secret:
            self.webhooks.register_inbound_key(default_integration_key, default_inbound_secret)
        if self.runtime:
            self.runtime.event_hook = self.webhooks.handle_events

    async def ensure_workflow_store(self) -> None:
        if self.workflow_store is None:
            self.workflow_store = await create_workflow_store()
            self._workflow_store_owned = True

    async def ensure_run_store(self) -> None:
        if self.run_store is None:
            await self.ensure_workflow_store()
            self.run_store = await create_run_store(self.workflow_store)
            self._run_store_owned = True

    async def ensure_idempotency(self) -> None:
        if self.idempotency is None:
            await self.ensure_workflow_store()
            self.idempotency = await create_idempotency_store(self.workflow_store)
            self._idempotency_owned = True

    async def ensure_runtime(self) -> None:
        if self.runtime is None:

            async def loader(
                workflow_id: str,
                version_id: Optional[str],
                tenant_id: Optional[str] = None,
            ) -> Workflow:
                return await _load_workflow(
                    self.workflow_store,
                    workflow_id,
                    version_id,
                    tenant_id=tenant_id,
                )

            executor_mode = (get_env("AGENT_EXECUTOR_MODE") or "").lower()
            executors: Dict[str, Any] = {}
            if executor_mode == "mock":
                executors["agent"] = MockAgentExecutor()
            elif AGENTS_AVAILABLE:
                executors["agent"] = AgentExecutor()

            self.runtime = MultiWorkflowRuntimeService.create(loader, executors=executors)
            self.runtime.event_hook = self.webhooks.handle_events

    async def close(self) -> None:
        await self.webhooks.stop_background_dispatcher()
        if self._idempotency_owned and self.idempotency:
            await self.idempotency.close()
        if self._run_store_owned and self.run_store:
            close_result = self.run_store.close()
            if isawaitable(close_result):
                await close_result
        if self._workflow_store_owned and self.workflow_store:
            await self.workflow_store.close()
        if self.runtime and self._runtime_started:
            await self.runtime.shutdown()


def _workflow_from_content(workflow_id: str, version_id: str, content: Dict[str, Any]) -> Workflow:
    nodes_raw = content.get("nodes") or []
    edges_raw = content.get("edges") or []
    if not nodes_raw:
        raise WorkflowConflictError("workflow content is missing nodes")

    nodes = {
        node["id"]: Node(
            node["id"],
            node.get("type", ""),
            node.get("config", {}),
        )
        for node in nodes_raw
        if isinstance(node, dict) and node.get("id")
    }
    if not nodes:
        raise WorkflowConflictError("workflow content is missing valid nodes")

    edges = [
        Edge(edge.get("source", ""), edge.get("target", ""))
        for edge in edges_raw
        if isinstance(edge, dict)
    ]

    return Workflow(
        id=workflow_id,
        version_id=version_id,
        nodes=nodes,
        edges=edges,
    )


async def _load_workflow(
    store,
    workflow_id: str,
    version_id: Optional[str],
    tenant_id: Optional[str] = None,
) -> Workflow:
    workflow = await store.get_workflow(workflow_id, tenant_id=tenant_id)
    if version_id:
        version = await store.get_version(version_id, tenant_id=tenant_id)
        if version.workflow_id != workflow_id:
            raise WorkflowNotFoundError("workflow version not found")
    else:
        if not workflow.active_version_id:
            raise WorkflowConflictError("workflow has no active published version")
        version = await store.get_version(workflow.active_version_id, tenant_id=tenant_id)
    return _workflow_from_content(workflow_id, version.version_id, version.content or {})


def create_app(
    workflow_store=None,
    run_store: Optional[Any] = None,
    runtime: Optional[MultiWorkflowRuntimeService] = None,
    default_inbound_secret: Optional[str] = None,
    default_integration_key: Optional[str] = None,
) -> Starlette:
    inbound_secret = default_inbound_secret
    if inbound_secret is None:
        inbound_secret = get_env("WEBHOOK_DEFAULT_INBOUND_SECRET")
    integration_key = default_integration_key or get_env("WEBHOOK_DEFAULT_INTEGRATION_KEY") or "default"
    ctx = ApiContext(
        run_store=run_store,
        workflow_store=workflow_store,
        runtime=runtime,
        default_inbound_secret=inbound_secret,
        default_integration_key=integration_key,
    )
    app: Starlette | None = None

    @asynccontextmanager
    async def lifespan(app: Starlette):
        await ctx.ensure_workflow_store()
        await ctx.ensure_run_store()
        await ctx.ensure_idempotency()
        await ctx.ensure_runtime()
        await ctx.runtime.startup()
        await ctx.webhooks.start_background_dispatcher()
        ctx._runtime_started = True
        app.state.runtime = ctx.runtime
        app.state.run_store = ctx.run_store
        app.state.workflow_store = ctx.workflow_store
        app.state.api_context = ctx
        try:
            yield
        finally:
            await ctx.close()

    def _correlation_id(request: Request) -> str:
        existing = getattr(request.state, "correlation_id", None)
        if existing:
            return existing
        incoming = request.headers.get("X-Correlation-Id")
        correlation_id = incoming or f"corr_{uuid.uuid4().hex[:12]}"
        request.state.correlation_id = correlation_id
        return correlation_id

    def _trace_id(request: Request) -> str:
        existing = getattr(request.state, "trace_id", None)
        if existing:
            return existing
        incoming = request.headers.get("X-Trace-Id")
        trace_id = incoming or f"trace_{uuid.uuid4().hex[:12]}"
        request.state.trace_id = trace_id
        return trace_id

    def _tenant_id(request: Request) -> str:
        existing = getattr(request.state, "tenant_id", None)
        if existing:
            return str(existing)
        incoming = request.headers.get("X-Tenant-Id")
        tenant_id = incoming or "local"
        request.state.tenant_id = tenant_id
        return tenant_id

    def _run_metadata(request: Request, payload_metadata: Any = None) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}
        if isinstance(payload_metadata, dict):
            for key, value in payload_metadata.items():
                if value is not None:
                    metadata[key] = value

        header_map = {
            "tenant_id": "X-Tenant-Id",
            "project_id": "X-Project-Id",
            "import_run_id": "X-Import-Run-Id",
            "user_id": "X-User-Id",
        }
        for field, header in header_map.items():
            incoming = request.headers.get(header)
            if incoming:
                metadata[field] = incoming

        metadata["correlation_id"] = str(metadata.get("correlation_id") or _correlation_id(request))
        metadata["trace_id"] = str(metadata.get("trace_id") or _trace_id(request))
        metadata["tenant_id"] = str(metadata.get("tenant_id") or _tenant_id(request))
        request.state.tenant_id = metadata["tenant_id"]
        return metadata

    def _json(request: Request, payload: Any, status_code: int = 200) -> JSONResponse:
        if isinstance(payload, dict):
            body = dict(payload)
        else:
            body = {"data": payload}
        body.setdefault("correlation_id", _correlation_id(request))
        return JSONResponse(body, status_code=status_code)

    def _error(
        request: Request,
        code: str,
        message: str,
        status_code: int,
        details: Optional[list[str]] = None,
    ) -> JSONResponse:
        error: Dict[str, Any] = {"code": code, "message": message}
        if details:
            error["details"] = details
        return JSONResponse(
            {"error": error, "correlation_id": _correlation_id(request)},
            status_code=status_code,
        )

    async def _await_if_needed(value: Any) -> Any:
        if isawaitable(value):
            return await value
        return value

    async def _run_store_save(run, tenant_id: str) -> None:
        await ctx.ensure_run_store()
        await _await_if_needed(ctx.run_store.save(run, tenant_id=tenant_id))

    async def _run_store_get(run_id: str, tenant_id: str):
        await ctx.ensure_run_store()
        return await _await_if_needed(ctx.run_store.get(run_id, tenant_id=tenant_id))

    async def _run_store_list(workflow_id: Optional[str], status: Optional[str], tenant_id: str):
        await ctx.ensure_run_store()
        return await _await_if_needed(ctx.run_store.list(workflow_id=workflow_id, status=status, tenant_id=tenant_id))

    async def _idempotent(
        request: Request,
        scope: str,
        handler: Callable[[], Awaitable[Response]],
    ) -> Response:
        if ctx.idempotency is None:
            await ctx.ensure_idempotency()
        if ctx.idempotency is None:
            return await handler()
        key = request.headers.get("Idempotency-Key")
        if not key:
            return await handler()
        tenant = _tenant_id(request)
        cached = await ctx.idempotency.get(key, scope, tenant_id=tenant)
        if cached:
            if cached.status_code == 204:
                return Response(status_code=204)
            return JSONResponse(cached.body, status_code=cached.status_code)

        response = await handler()
        if 200 <= response.status_code < 300:
            payload: Any = None
            body = response.body
            if body:
                try:
                    payload = json.loads(body.decode("utf-8"))
                except Exception:
                    payload = body.decode("utf-8", errors="ignore")
            await ctx.idempotency.set(key, scope, response.status_code, payload, tenant_id=tenant)
        return response

    def _validate_draft(draft: Dict[str, Any]) -> list[str]:
        errors: list[str] = []
        nodes_raw = draft.get("nodes")
        edges_raw = draft.get("edges")
        if not isinstance(nodes_raw, list) or not nodes_raw:
            errors.append("draft.nodes must be a non-empty array")
            return errors
        if not isinstance(edges_raw, list):
            errors.append("draft.edges must be an array")
            return errors

        node_ids: set[str] = set()
        start_nodes: set[str] = set()
        end_nodes: set[str] = set()
        for idx, node in enumerate(nodes_raw):
            if not isinstance(node, dict):
                errors.append(f"draft.nodes[{idx}] must be an object")
                continue
            node_id = node.get("id")
            node_type = node.get("type")
            if not node_id:
                errors.append(f"draft.nodes[{idx}].id is required")
                continue
            if node_id in node_ids:
                errors.append(f"duplicate node id: {node_id}")
            node_ids.add(str(node_id))
            if not node_type:
                errors.append(f"draft.nodes[{idx}].type is required")
                continue
            if node_type == "start":
                start_nodes.add(str(node_id))
            if node_type == "end":
                end_nodes.add(str(node_id))

        for idx, edge in enumerate(edges_raw):
            if not isinstance(edge, dict):
                errors.append(f"draft.edges[{idx}] must be an object")
                continue
            source = edge.get("source")
            target = edge.get("target")
            if not source or not target:
                errors.append(f"draft.edges[{idx}] requires source and target")
                continue
            if source not in node_ids or target not in node_ids:
                errors.append(f"edge {source}->{target} references unknown node")

        if not start_nodes:
            errors.append("draft must include a start node")
        if not end_nodes:
            errors.append("draft must include an end node")

        if start_nodes and end_nodes:
            adjacency: Dict[str, list[str]] = {node_id: [] for node_id in node_ids}
            for edge in edges_raw:
                if not isinstance(edge, dict):
                    continue
                source = edge.get("source")
                target = edge.get("target")
                if source in adjacency and target:
                    adjacency[source].append(str(target))

            visited: set[str] = set()
            queue = list(start_nodes)
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                for neighbor in adjacency.get(current, []):
                    if neighbor not in visited:
                        queue.append(neighbor)

            if not any(node_id in visited for node_id in end_nodes):
                errors.append("draft must have a path from start to end")

        return errors

    async def _require_runtime() -> MultiWorkflowRuntimeService:
        if ctx.runtime is None:
            await ctx.ensure_workflow_store()
            await ctx.ensure_run_store()
            await ctx.ensure_runtime()
        if not ctx._runtime_started:
            await ctx.runtime.startup()
            await ctx.webhooks.start_background_dispatcher()
            ctx._runtime_started = True
        if app is not None:
            app.state.runtime = ctx.runtime
            app.state.run_store = ctx.run_store
            app.state.workflow_store = ctx.workflow_store
        return ctx.runtime

    async def create_workflow(request: Request) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)
        name = payload.get("name")
        if not name:
            return _error(request, "INVALID_ARGUMENT", "name is required", 400)
        draft = payload.get("draft") or {}
        if not isinstance(draft, dict):
            return _error(request, "INVALID_ARGUMENT", "draft must be an object", 400)
        draft.setdefault("nodes", [])
        draft.setdefault("edges", [])
        draft.setdefault("variables_schema", {})
        workflow = await ctx.workflow_store.create_workflow(
            name=name,
            description=payload.get("description"),
            draft=draft,
            tenant_id=_tenant_id(request),
        )
        return _json(request, workflow_to_dict(workflow), status_code=201)

    async def list_workflows(request: Request) -> JSONResponse:
        limit_raw = request.query_params.get("limit")
        limit = 50
        if limit_raw:
            try:
                limit = max(1, min(200, int(limit_raw)))
            except ValueError:
                return _error(request, "INVALID_ARGUMENT", "limit must be an integer", 400)
        workflows = await ctx.workflow_store.list_workflows(limit=limit, tenant_id=_tenant_id(request))
        return _json(
            request,
            {"items": [workflow_summary_to_dict(item) for item in workflows], "next_cursor": None}
        )

    async def update_workflow(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        payload = await request.json()
        if not isinstance(payload, dict):
            return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)
        update_name = "name" in payload
        update_description = "description" in payload
        name = payload.get("name")
        description = payload.get("description")
        if not update_name and not update_description:
            return _error(request, "INVALID_ARGUMENT", "name or description required", 400)
        if update_name and (not isinstance(name, str) or not name.strip()):
            return _error(request, "INVALID_ARGUMENT", "name must be a non-empty string", 400)
        try:
            workflow = await ctx.workflow_store.update_meta(
                workflow_id,
                name=name,
                description=description,
                update_name=update_name,
                update_description=update_description,
                tenant_id=_tenant_id(request),
            )
        except WorkflowNotFoundError:
            return _error(request, "NOT_FOUND", "workflow not found", 404)
        return _json(request, workflow_to_dict(workflow))

    async def get_workflow(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        try:
            workflow = await ctx.workflow_store.get_workflow(workflow_id, tenant_id=_tenant_id(request))
        except WorkflowNotFoundError:
            return _error(request, "NOT_FOUND", "workflow not found", 404)
        return _json(request, workflow_to_dict(workflow))

    async def delete_workflow(request: Request) -> Response:
        workflow_id = request.path_params["workflow_id"]
        try:
            await ctx.workflow_store.delete_workflow(workflow_id, tenant_id=_tenant_id(request))
        except WorkflowNotFoundError:
            return _error(request, "NOT_FOUND", "workflow not found", 404)
        return Response(status_code=204)

    async def update_workflow_draft(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        payload = await request.json()
        if not isinstance(payload, dict):
            return _error(request, "INVALID_ARGUMENT", "draft must be an object", 400)
        if "draft" in payload:
            draft = payload.get("draft")
            if not isinstance(draft, dict):
                return _error(request, "INVALID_ARGUMENT", "draft must be an object", 400)
        else:
            draft = payload
        draft.setdefault("nodes", [])
        draft.setdefault("edges", [])
        draft.setdefault("variables_schema", {})
        try:
            workflow = await ctx.workflow_store.update_draft(workflow_id, draft, tenant_id=_tenant_id(request))
        except WorkflowNotFoundError:
            return _error(request, "NOT_FOUND", "workflow not found", 404)
        return _json(request, workflow_to_dict(workflow))

    async def publish_workflow(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        try:
            tenant = _tenant_id(request)
            workflow = await ctx.workflow_store.get_workflow(workflow_id, tenant_id=tenant)
            errors = _validate_draft(workflow.draft)
            if errors:
                return _error(request, "INVALID_ARGUMENT", "draft is invalid", 400, details=errors)
            version = await ctx.workflow_store.publish(workflow_id, tenant_id=tenant)
        except WorkflowNotFoundError:
            return _error(request, "NOT_FOUND", "workflow not found", 404)
        except WorkflowConflictError as exc:
            return _error(request, "INVALID_ARGUMENT", str(exc), 400)
        return _json(request, workflow_version_to_dict(version))

    async def rollback_workflow(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        try:
            workflow = await ctx.workflow_store.rollback(workflow_id, tenant_id=_tenant_id(request))
        except WorkflowNotFoundError:
            return _error(request, "NOT_FOUND", "workflow not found", 404)
        except WorkflowConflictError as exc:
            return _error(request, "INVALID_ARGUMENT", str(exc), 400)
        return _json(request, workflow_to_dict(workflow))

    async def list_workflow_versions(request: Request) -> JSONResponse:
        workflow_id = request.path_params["workflow_id"]
        limit_raw = request.query_params.get("limit", "50")
        try:
            limit = int(limit_raw)
        except ValueError:
            return _error(request, "INVALID_ARGUMENT", "limit must be an integer", 400)
        if limit < 1 or limit > 200:
            return _error(request, "INVALID_ARGUMENT", "limit must be between 1 and 200", 400)
        try:
            versions = await ctx.workflow_store.list_versions(
                workflow_id,
                limit=limit,
                tenant_id=_tenant_id(request),
            )
        except WorkflowNotFoundError:
            return _error(request, "NOT_FOUND", "workflow not found", 404)
        return _json(
            request,
            {
                "items": [workflow_version_to_dict(version) for version in versions],
                "next_cursor": None,
            }
        )

    async def start_run(request: Request) -> Response:
        workflow_id = request.path_params["workflow_id"]

        async def _start_impl() -> Response:
            payload = await request.json()
            if not isinstance(payload, dict):
                return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)
            inputs = payload.get("inputs", {})
            if not isinstance(inputs, dict):
                return _error(request, "INVALID_ARGUMENT", "inputs must be an object", 400)
            version_id = payload.get("version_id") or payload.get("workflow_version_id")
            metadata = payload.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                return _error(request, "INVALID_ARGUMENT", "metadata must be an object", 400)
            mode = payload.get("mode")
            allowed_modes = {"live", "test", "sync", "async"}
            if mode is not None and (not isinstance(mode, str) or mode not in allowed_modes):
                return _error(
                    request,
                    "INVALID_ARGUMENT",
                    "mode must be one of: live, test, sync, async",
                    400,
                )
            try:
                run_metadata = _run_metadata(request, metadata)
                tenant = str(run_metadata.get("tenant_id") or _tenant_id(request))
                await _load_workflow(
                    ctx.workflow_store,
                    workflow_id,
                    version_id,
                    tenant_id=tenant,
                )
                runtime = await _require_runtime()
                run = await runtime.start_run(
                    workflow_id,
                    version_id,
                    inputs,
                    mode=mode,
                    metadata=run_metadata,
                )
            except WorkflowNotFoundError:
                return _error(request, "NOT_FOUND", "workflow not found", 404)
            except WorkflowConflictError as exc:
                return _error(request, "INVALID_ARGUMENT", str(exc), 400)
            await _run_store_save(run, tenant_id=tenant)
            return _json(request, run_to_dict(run), status_code=201)

        return await _idempotent(request, f"run_start:{workflow_id}", _start_impl)

    async def get_run(request: Request) -> JSONResponse:
        run = await _run_store_get(request.path_params["run_id"], tenant_id=_tenant_id(request))
        if not run:
            return _error(request, "NOT_FOUND", "run not found", 404)
        return _json(request, run_to_dict(run))

    async def list_runs(request: Request) -> JSONResponse:
        workflow_id = request.query_params.get("workflow_id")
        status = request.query_params.get("status")
        runs = await _run_store_list(
            workflow_id=workflow_id,
            status=status,
            tenant_id=_tenant_id(request),
        )
        return _json(request, {"items": [run_to_dict(run) for run in runs], "next_cursor": None})

    async def cancel_run(request: Request) -> Response:
        run_id = request.path_params["run_id"]

        async def _cancel_impl() -> Response:
            tenant = _tenant_id(request)
            run = await _run_store_get(run_id, tenant_id=tenant)
            if not run:
                return _error(request, "NOT_FOUND", "run not found", 404)
            run.status = "CANCELLED"
            runtime = await _require_runtime()
            await runtime._publish_with_snapshot(
                run,
                [
                    RuntimeEvent(
                        type="run_cancelled",
                        run_id=run.id,
                        workflow_id=run.workflow_id,
                        version_id=run.version_id,
                    )
                ],
            )
            await _run_store_save(run, tenant_id=tenant)
            return _json(request, run_to_dict(run))

        return await _idempotent(request, f"run_cancel:{run_id}", _cancel_impl)

    async def rerun_node(request: Request) -> Response:
        run_id = request.path_params["run_id"]

        async def _rerun_impl() -> Response:
            tenant = _tenant_id(request)
            run = await _run_store_get(run_id, tenant_id=tenant)
            if not run:
                return _error(request, "NOT_FOUND", "run not found", 404)
            payload = await request.json()
            if not isinstance(payload, dict):
                return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)
            node_id = payload.get("node_id")
            scope = payload.get("scope")
            if not node_id or not scope:
                return _error(request, "INVALID_ARGUMENT", "node_id and scope required", 400)
            try:
                runtime = await _require_runtime()
                await runtime.rerun_node(run, node_id=node_id, scope=scope)
            except WorkflowNotFoundError:
                return _error(request, "NOT_FOUND", "workflow not found", 404)
            except ValueError as exc:
                return _error(request, "INVALID_ARGUMENT", str(exc), 400)
            await _run_store_save(run, tenant_id=tenant)
            return _json(request, run_to_dict(run))

        return await _idempotent(request, f"run_rerun:{run_id}", _rerun_impl)

    async def resume_interrupt(request: Request) -> Response:
        run_id = request.path_params["run_id"]
        interrupt_id = request.path_params["interrupt_id"]

        async def _resume_impl() -> Response:
            tenant = _tenant_id(request)
            run = await _run_store_get(run_id, tenant_id=tenant)
            if not run:
                return _error(request, "NOT_FOUND", "run not found", 404)
            payload = await request.json()
            if not isinstance(payload, dict):
                return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)
            input_data = payload.get("input")
            files = payload.get("files")
            try:
                runtime = await _require_runtime()
                await runtime.resume_interrupt(run, interrupt_id, input_data, files)
            except ValueError as exc:
                return _error(request, "INVALID_ARGUMENT", str(exc), 400)
            await _run_store_save(run, tenant_id=tenant)
            return _json(request, run_to_dict(run))

        return await _idempotent(
            request,
            f"interrupt_resume:{run_id}:{interrupt_id}",
            _resume_impl,
        )

    async def cancel_interrupt(request: Request) -> Response:
        run_id = request.path_params["run_id"]
        interrupt_id = request.path_params["interrupt_id"]

        async def _cancel_impl() -> Response:
            tenant = _tenant_id(request)
            run = await _run_store_get(run_id, tenant_id=tenant)
            if not run:
                return _error(request, "NOT_FOUND", "run not found", 404)
            interrupt = run.interrupts.get(interrupt_id)
            if not interrupt:
                return _error(request, "NOT_FOUND", "interrupt not found", 404)
            interrupt.status = "CANCELLED"
            run.status = "FAILED"
            runtime = await _require_runtime()
            await runtime._publish_with_snapshot(
                run,
                [
                    RuntimeEvent(
                        type="run_failed",
                        run_id=run.id,
                        workflow_id=run.workflow_id,
                        version_id=run.version_id,
                        node_id=interrupt.node_id,
                        payload={"reason": "interrupt_cancelled"},
                    )
                ],
            )
            await _run_store_save(run, tenant_id=tenant)
            return _json(request, interrupt_to_dict(interrupt))

        return await _idempotent(
            request,
            f"interrupt_cancel:{run_id}:{interrupt_id}",
            _cancel_impl,
        )

    async def stream(request: Request) -> Response:
        run_id = request.path_params["run_id"]
        run = await _run_store_get(run_id, tenant_id=_tenant_id(request))
        if not run:
            return _error(request, "NOT_FOUND", "run not found", 404)
        last_event_id = request.headers.get("Last-Event-ID")
        runtime = await _require_runtime()
        generator = _event_stream(
            run_id,
            runtime.store,
            runtime.bus,
            last_event_id,
            runtime.store.get_snapshot,
        )
        return StreamingResponse(generator, media_type="text/event-stream")

    async def inbound_webhook(request: Request) -> JSONResponse:
        integration_key = request.path_params["integration_key"]
        body = await request.body()
        if body:
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                return _error(request, "INVALID_ARGUMENT", "invalid json payload", 400)
        else:
            payload = {}
        runtime = await _require_runtime()
        await ctx.ensure_run_store()
        status, response = await ctx.webhooks.handle_inbound(
            integration_key,
            dict(request.headers),
            body,
            payload,
            ctx.run_store,
            runtime,
        )
        return _json(request, response, status_code=status)

    async def list_outbound(request: Request) -> JSONResponse:
        subs = ctx.webhooks.list_outbound()
        return _json(
            request,
            {
                "items": [
                    {
                        "subscription_id": sub.id,
                        "url": sub.url,
                        "event_types": sub.event_types,
                        "is_active": sub.is_active,
                    }
                    for sub in subs
                ],
                "next_cursor": None,
            }
        )

    async def register_outbound(request: Request) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)
        url = payload.get("url")
        event_types = payload.get("event_types")
        secret = payload.get("secret")
        if not url or not isinstance(event_types, list) or not event_types:
            return _error(request, "INVALID_ARGUMENT", "url and event_types required", 400)
        sub = ctx.webhooks.register_outbound(url, list(event_types), secret=secret)
        return _json(
            request,
            {
                "subscription_id": sub.id,
                "url": sub.url,
                "event_types": sub.event_types,
                "is_active": sub.is_active,
            },
            status_code=201,
        )

    async def delete_outbound(request: Request) -> Response:
        sub_id = request.path_params["subscription_id"]
        if not ctx.webhooks.delete_outbound(sub_id):
            return _error(request, "NOT_FOUND", "subscription not found", 404)
        return Response(status_code=204)

    async def health(_: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    async def openapi_spec(_: Request) -> PlainTextResponse:
        if not _OPENAPI_SPEC_PATH.exists():
            return PlainTextResponse("openapi spec not found", status_code=404)
        return PlainTextResponse(_OPENAPI_SPEC_PATH.read_text(encoding="utf-8"), media_type="application/yaml")

    async def api_reference(_: Request) -> PlainTextResponse:
        if not _API_REFERENCE_PATH.exists():
            return PlainTextResponse("api reference not found", status_code=404)
        return PlainTextResponse(_API_REFERENCE_PATH.read_text(encoding="utf-8"), media_type="text/markdown")

    def _public_doc_urls(request: Request) -> Dict[str, str]:
        base_url = str(request.base_url).rstrip("/")
        return {
            "integration_kit_markdown": f"{base_url}/agent-integration-kit",
            "integration_kit_json": f"{base_url}/agent-integration-kit.json",
            "integration_test_ui": f"{base_url}/agent-integration-test",
            "integration_test_json": f"{base_url}/agent-integration-test.json",
            "validate_draft": f"{base_url}/agent-integration-test/validate-draft",
            "openapi": f"{base_url}/openapi.yaml",
            "api_reference": f"{base_url}/api-reference",
            "workflow_authoring_guide": f"{base_url}/workflow-authoring-guide",
            "workflow_draft_schema": f"{base_url}/schemas/workflow-draft.schema.json",
            "workflow_export_schema": f"{base_url}/schemas/workflow-export-v1.schema.json",
        }

    def _integration_check_report(request: Request) -> Dict[str, Any]:
        checks: list[dict[str, Any]] = []

        def add_check(check_id: str, description: str, ok: bool, detail: str) -> None:
            checks.append(
                {
                    "id": check_id,
                    "description": description,
                    "ok": ok,
                    "detail": detail,
                }
            )

        openapi_text = ""
        if _OPENAPI_SPEC_PATH.exists():
            try:
                openapi_text = _OPENAPI_SPEC_PATH.read_text(encoding="utf-8")
                add_check("openapi_exists", "OpenAPI file is available", True, "ok")
            except Exception as exc:
                add_check("openapi_exists", "OpenAPI file is available", False, str(exc))
        else:
            add_check("openapi_exists", "OpenAPI file is available", False, "missing docs/api/openapi.yaml")

        if _API_REFERENCE_PATH.exists():
            add_check("api_reference_exists", "API reference is available", True, "ok")
        else:
            add_check("api_reference_exists", "API reference is available", False, "missing docs/api/reference.md")

        if _WORKFLOW_AUTHORING_GUIDE_PATH.exists():
            add_check(
                "workflow_authoring_guide_exists",
                "Workflow authoring guide is available",
                True,
                "ok",
            )
        else:
            add_check(
                "workflow_authoring_guide_exists",
                "Workflow authoring guide is available",
                False,
                "missing docs/architecture/workflow-authoring-agents.md",
            )

        draft_schema = None
        if _WORKFLOW_DRAFT_SCHEMA_PATH.exists():
            try:
                draft_schema = json.loads(_WORKFLOW_DRAFT_SCHEMA_PATH.read_text(encoding="utf-8"))
                add_check("workflow_draft_schema_valid_json", "Workflow draft schema is valid JSON", True, "ok")
            except Exception as exc:
                add_check(
                    "workflow_draft_schema_valid_json",
                    "Workflow draft schema is valid JSON",
                    False,
                    str(exc),
                )
        else:
            add_check(
                "workflow_draft_schema_valid_json",
                "Workflow draft schema is valid JSON",
                False,
                "missing docs/api/schemas/workflow-draft.schema.json",
            )

        export_schema = None
        if _WORKFLOW_EXPORT_SCHEMA_PATH.exists():
            try:
                export_schema = json.loads(_WORKFLOW_EXPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
                add_check("workflow_export_schema_valid_json", "Workflow export schema is valid JSON", True, "ok")
            except Exception as exc:
                add_check(
                    "workflow_export_schema_valid_json",
                    "Workflow export schema is valid JSON",
                    False,
                    str(exc),
                )
        else:
            add_check(
                "workflow_export_schema_valid_json",
                "Workflow export schema is valid JSON",
                False,
                "missing docs/api/schemas/workflow-export-v1.schema.json",
            )

        required_openapi_paths = (
            "/agent-integration-kit",
            "/agent-integration-kit.json",
            "/agent-integration-test",
            "/agent-integration-test.json",
            "/agent-integration-test/validate-draft",
            "/workflow-authoring-guide",
            "/schemas/workflow-draft.schema.json",
            "/schemas/workflow-export-v1.schema.json",
        )
        missing_paths = [path for path in required_openapi_paths if path not in openapi_text]
        add_check(
            "openapi_has_integration_paths",
            "OpenAPI includes integration kit/test endpoints",
            len(missing_paths) == 0,
            "ok" if not missing_paths else f"missing: {', '.join(missing_paths)}",
        )

        sample_valid_draft = {
            "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}],
            "edges": [{"source": "start", "target": "end"}],
            "variables_schema": {},
        }
        valid_errors = _validate_draft(sample_valid_draft)
        add_check(
            "sample_valid_draft_passes",
            "Sample valid draft passes runtime validation",
            len(valid_errors) == 0,
            "ok" if not valid_errors else "; ".join(valid_errors),
        )

        sample_invalid_draft = {"nodes": [{"id": "start", "type": "start"}], "edges": []}
        invalid_errors = _validate_draft(sample_invalid_draft)
        add_check(
            "sample_invalid_draft_fails",
            "Sample invalid draft fails runtime validation",
            len(invalid_errors) > 0,
            "ok" if invalid_errors else "expected validation errors, got none",
        )

        if isinstance(export_schema, dict):
            export_const = (
                export_schema.get("properties", {})
                .get("schema_version", {})
                .get("const")
            )
            add_check(
                "export_schema_version_const",
                "Export schema pins schema_version=workflow_export_v1",
                export_const == "workflow_export_v1",
                f"const={export_const!r}",
            )

        if isinstance(draft_schema, dict):
            node_types = (
                draft_schema.get("$defs", {})
                .get("nodeType", {})
                .get("enum", [])
            )
            add_check(
                "draft_schema_node_types",
                "Draft schema declares all supported node types",
                isinstance(node_types, list) and "start" in node_types and "end" in node_types,
                f"node_types_count={len(node_types) if isinstance(node_types, list) else 0}",
            )

        passed = len([check for check in checks if check["ok"]])
        total = len(checks)

        return {
            "title": "WorkCore Agent Integration Test",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "urls": _public_doc_urls(request),
            "summary": {
                "status": "PASS" if passed == total else "FAIL",
                "passed": passed,
                "failed": total - passed,
                "total": total,
            },
            "checks": checks,
        }

    async def workflow_authoring_guide(_: Request) -> PlainTextResponse:
        if not _WORKFLOW_AUTHORING_GUIDE_PATH.exists():
            return PlainTextResponse("workflow authoring guide not found", status_code=404)
        return PlainTextResponse(
            _WORKFLOW_AUTHORING_GUIDE_PATH.read_text(encoding="utf-8"),
            media_type="text/markdown",
        )

    async def workflow_draft_schema(_: Request) -> Response:
        if not _WORKFLOW_DRAFT_SCHEMA_PATH.exists():
            return PlainTextResponse("workflow draft schema not found", status_code=404)
        try:
            payload = json.loads(_WORKFLOW_DRAFT_SCHEMA_PATH.read_text(encoding="utf-8"))
        except Exception:
            return PlainTextResponse("workflow draft schema is invalid", status_code=500)
        return JSONResponse(payload)

    async def workflow_export_schema(_: Request) -> Response:
        if not _WORKFLOW_EXPORT_SCHEMA_PATH.exists():
            return PlainTextResponse("workflow export schema not found", status_code=404)
        try:
            payload = json.loads(_WORKFLOW_EXPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
        except Exception:
            return PlainTextResponse("workflow export schema is invalid", status_code=500)
        return JSONResponse(payload)

    async def agent_integration_kit(request: Request) -> PlainTextResponse:
        urls = _public_doc_urls(request)
        updated_at = datetime.now(timezone.utc).isoformat()
        lines = [
            "# WorkCore Agent Integration Kit",
            "",
            f"Updated at: {updated_at}",
            "",
            "Use this document as a single starting point for external agent integrations.",
            "",
            "## Required URLs",
            f"- OpenAPI: {urls['openapi']}",
            f"- API reference: {urls['api_reference']}",
            f"- Workflow authoring guide: {urls['workflow_authoring_guide']}",
            f"- Workflow draft schema: {urls['workflow_draft_schema']}",
            f"- Workflow export schema: {urls['workflow_export_schema']}",
            f"- Integration test UI: {urls['integration_test_ui']}",
            f"- Integration test JSON: {urls['integration_test_json']}",
            f"- Draft validator endpoint: {urls['validate_draft']}",
            "",
            "## Machine-readable bundle",
            f"- JSON bundle: {urls['integration_kit_json']}",
            "",
            "## Minimum integration steps",
            "1. Read OpenAPI and API reference.",
            "2. Validate workflow payloads with the provided schemas.",
            "3. Follow the workflow authoring guide before publish/run.",
            "4. Run integration checks and ensure status=PASS.",
            "5. Use `/workflows`, `/publish`, and `/runs` lifecycle endpoints.",
        ]
        return PlainTextResponse("\n".join(lines), media_type="text/markdown")

    async def agent_integration_kit_json(request: Request) -> JSONResponse:
        if not _WORKFLOW_AUTHORING_GUIDE_PATH.exists():
            return _error(request, "NOT_FOUND", "workflow authoring guide not found", 404)
        if not _API_REFERENCE_PATH.exists():
            return _error(request, "NOT_FOUND", "api reference not found", 404)
        if not _WORKFLOW_DRAFT_SCHEMA_PATH.exists():
            return _error(request, "NOT_FOUND", "workflow draft schema not found", 404)
        if not _WORKFLOW_EXPORT_SCHEMA_PATH.exists():
            return _error(request, "NOT_FOUND", "workflow export schema not found", 404)

        try:
            draft_schema = json.loads(_WORKFLOW_DRAFT_SCHEMA_PATH.read_text(encoding="utf-8"))
            export_schema = json.loads(_WORKFLOW_EXPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
        except Exception:
            return _error(request, "INTERNAL", "invalid local schema files", 500)

        payload = {
            "title": "WorkCore Agent Integration Kit",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "urls": _public_doc_urls(request),
            "integration_test": _integration_check_report(request),
            "docs": {
                "api_reference_markdown": _API_REFERENCE_PATH.read_text(encoding="utf-8"),
                "workflow_authoring_guide_markdown": _WORKFLOW_AUTHORING_GUIDE_PATH.read_text(encoding="utf-8"),
            },
            "schemas": {
                "workflow_draft": draft_schema,
                "workflow_export_v1": export_schema,
            },
        }
        return _json(request, payload)

    async def agent_integration_test(request: Request) -> PlainTextResponse:
        html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>WorkCore Agent Integration Test</title>
  <style>
    body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 980px; margin: 24px auto; padding: 0 16px; }
    .muted { color: #666; }
    .row { display: flex; gap: 8px; align-items: center; margin: 6px 0; flex-wrap: wrap; }
    .ok { color: #0a7d31; font-weight: 600; }
    .fail { color: #b00020; font-weight: 600; }
    textarea { width: 100%; min-height: 220px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    pre { background: #f7f7f8; padding: 12px; border-radius: 8px; overflow: auto; }
    button { padding: 8px 12px; cursor: pointer; }
    .card { border: 1px solid #e6e6e8; border-radius: 8px; padding: 12px; margin-top: 12px; }
  </style>
</head>
<body>
  <h1>WorkCore Agent Integration Test</h1>
  <p class="muted">Use this page to verify integration readiness and validate workflow drafts before publish.</p>
  <div class="row">
    <button id="refresh">Run checks</button>
    <a href="/agent-integration-test.json" target="_blank" rel="noopener noreferrer">Open JSON report</a>
    <a href="/agent-integration-kit" target="_blank" rel="noopener noreferrer">Open integration kit</a>
  </div>
  <div id="summary" class="card muted">Loading...</div>
  <div id="checks" class="card"></div>

  <h2>Draft Validator</h2>
  <p class="muted">Paste draft JSON and validate against runtime publish rules.</p>
  <textarea id="draftInput">{\n  "nodes": [\n    { "id": "start", "type": "start" },\n    { "id": "end", "type": "end" }\n  ],\n  "edges": [\n    { "source": "start", "target": "end" }\n  ],\n  "variables_schema": {}\n}</textarea>
  <div class="row">
    <button id="validate">Validate draft</button>
  </div>
  <pre id="validateOutput">No validation run yet.</pre>

  <script>
    const summaryEl = document.getElementById('summary');
    const checksEl = document.getElementById('checks');
    const validateOutput = document.getElementById('validateOutput');
    const draftInput = document.getElementById('draftInput');

    async function runChecks() {
      summaryEl.textContent = 'Loading...';
      checksEl.innerHTML = '';
      const response = await fetch('/agent-integration-test.json');
      const payload = await response.json();
      const summary = payload.summary || {};
      const statusClass = summary.status === 'PASS' ? 'ok' : 'fail';
      summaryEl.innerHTML = '<div class=\"row\"><span class=\"' + statusClass + '\">' + (summary.status || 'UNKNOWN') + '</span>' +
        '<span>Passed: ' + (summary.passed ?? 0) + '/' + (summary.total ?? 0) + '</span>' +
        '<span class=\"muted\">Generated: ' + (payload.generated_at || '') + '</span></div>';
      const checks = payload.checks || [];
      checks.forEach((check) => {
        const row = document.createElement('div');
        row.className = 'row';
        const cls = check.ok ? 'ok' : 'fail';
        row.innerHTML = '<span class=\"' + cls + '\">' + (check.ok ? 'PASS' : 'FAIL') + '</span>' +
          '<span>' + check.id + '</span>' +
          '<span class=\"muted\">' + (check.description || '') + '</span>' +
          '<span class=\"muted\">' + (check.detail || '') + '</span>';
        checksEl.appendChild(row);
      });
    }

    async function validateDraft() {
      let parsed;
      try {
        parsed = JSON.parse(draftInput.value || '{}');
      } catch (error) {
        validateOutput.textContent = 'Invalid JSON: ' + (error?.message || String(error));
        return;
      }
      const response = await fetch('/agent-integration-test/validate-draft', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ draft: parsed })
      });
      const payload = await response.json();
      validateOutput.textContent = JSON.stringify(payload, null, 2);
    }

    document.getElementById('refresh').addEventListener('click', runChecks);
    document.getElementById('validate').addEventListener('click', validateDraft);
    runChecks();
  </script>
</body>
</html>"""
        return PlainTextResponse(html, media_type="text/html")

    async def agent_integration_test_json(request: Request) -> JSONResponse:
        return _json(request, _integration_check_report(request))

    async def agent_validate_draft(request: Request) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)
        draft = payload.get("draft", payload)
        if not isinstance(draft, dict):
            return _error(request, "INVALID_ARGUMENT", "draft must be an object", 400)
        errors = _validate_draft(draft)
        return _json(
            request,
            {
                "valid": len(errors) == 0,
                "errors": errors,
            },
        )

    routes = [
        Route("/health", health),
        Route("/openapi.yaml", openapi_spec),
        Route("/api-reference", api_reference),
        Route("/workflow-authoring-guide", workflow_authoring_guide),
        Route("/schemas/workflow-draft.schema.json", workflow_draft_schema),
        Route("/schemas/workflow-export-v1.schema.json", workflow_export_schema),
        Route("/agent-integration-kit", agent_integration_kit),
        Route("/agent-integration-kit.json", agent_integration_kit_json),
        Route("/agent-integration-test", agent_integration_test),
        Route("/agent-integration-test.json", agent_integration_test_json),
        Route("/agent-integration-test/validate-draft", agent_validate_draft, methods=["POST"]),
        Route("/workflows", list_workflows, methods=["GET"]),
        Route("/workflows", create_workflow, methods=["POST"]),
        Route("/workflows/{workflow_id}", update_workflow, methods=["PATCH"]),
        Route("/workflows/{workflow_id}", get_workflow, methods=["GET"]),
        Route("/workflows/{workflow_id}", delete_workflow, methods=["DELETE"]),
        Route("/workflows/{workflow_id}/draft", update_workflow_draft, methods=["PUT"]),
        Route("/workflows/{workflow_id}/publish", publish_workflow, methods=["POST"]),
        Route("/workflows/{workflow_id}/rollback", rollback_workflow, methods=["POST"]),
        Route("/workflows/{workflow_id}/versions", list_workflow_versions, methods=["GET"]),
        Route("/workflows/{workflow_id}/runs", start_run, methods=["POST"]),
        Route("/runs", list_runs, methods=["GET"]),
        Route("/runs/{run_id}", get_run, methods=["GET"]),
        Route("/runs/{run_id}/cancel", cancel_run, methods=["POST"]),
        Route("/runs/{run_id}/rerun-node", rerun_node, methods=["POST"]),
        Route("/runs/{run_id}/interrupts/{interrupt_id}/resume", resume_interrupt, methods=["POST"]),
        Route("/runs/{run_id}/interrupts/{interrupt_id}/cancel", cancel_interrupt, methods=["POST"]),
        Route("/runs/{run_id}/stream", stream, methods=["GET"]),
        Route("/webhooks/inbound/{integration_key}", inbound_webhook, methods=["POST"]),
        Route("/webhooks/outbound", list_outbound, methods=["GET"]),
        Route("/webhooks/outbound", register_outbound, methods=["POST"]),
        Route("/webhooks/outbound/{subscription_id}", delete_outbound, methods=["DELETE"]),
    ]

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.api_context = ctx
    api_auth_token = get_env("WORKCORE_API_AUTH_TOKEN")

    if api_auth_token:
        class ApiTokenMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                if request.method == "OPTIONS":
                    return await call_next(request)
                if (
                    request.url.path == "/health"
                    or request.url.path == "/openapi.yaml"
                    or request.url.path == "/api-reference"
                    or request.url.path == "/workflow-authoring-guide"
                    or request.url.path == "/agent-integration-kit"
                    or request.url.path == "/agent-integration-kit.json"
                    or request.url.path == "/agent-integration-test"
                    or request.url.path == "/agent-integration-test.json"
                    or request.url.path == "/agent-integration-test/validate-draft"
                    or request.url.path.startswith("/schemas/")
                    or request.url.path.startswith("/webhooks/inbound/")
                ):
                    return await call_next(request)

                auth_header = request.headers.get("Authorization", "")
                expected = f"Bearer {api_auth_token}"
                if auth_header != expected:
                    return _error(request, "UNAUTHORIZED", "missing or invalid bearer token", 401)
                return await call_next(request)

        app.add_middleware(ApiTokenMiddleware)

    cors_origins = (
        get_env("CORS_ALLOW_ORIGINS")
        or "http://localhost:5173,http://127.0.0.1:5173,http://builder.localhost:8080"
    )
    allow_origins = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app
