from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import uuid
from collections import deque
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

from apps.orchestrator.api.artifact_store import (
    ArtifactAccessDeniedError,
    ArtifactExpiredError,
    ArtifactNotFoundError,
    create_artifact_store,
)
from apps.orchestrator.api.capability_store import CapabilityConflictError, create_capability_store
from apps.orchestrator.api.handoff_store import create_handoff_store
from apps.orchestrator.api.idempotency import IdempotencyStore, create_idempotency_store
from apps.orchestrator.api.ledger_store import create_run_ledger_store, runtime_events_to_ledger_entries
from apps.orchestrator.api.serializers import (
    capability_to_dict,
    handoff_to_dict,
    interrupt_to_dict,
    orchestrator_config_to_dict,
    project_to_dict,
    run_ledger_entry_to_dict,
    run_to_dict,
    workflow_definition_to_dict,
    workflow_summary_to_dict,
    workflow_to_dict,
    workflow_version_to_dict,
)
from apps.orchestrator.api.store import create_run_store
from apps.orchestrator.api.workflow_store import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    create_workflow_store,
    no_inline_projection_defaults,
)
from apps.orchestrator.executors import (
    AGENTS_AVAILABLE,
    AgentExecutor,
    IntegrationHTTPEgressPolicy,
    IntegrationHTTPExecutor,
    MockAgentExecutor,
)
from apps.orchestrator.orchestrator_runtime import (
    OrchestratorRuntimeError,
    ProjectConflictError,
    ProjectOrchestratorRuntime,
    create_orchestration_store,
)
from apps.orchestrator.project_router import ProjectRouter, ProjectRouterError, RoutingRequest
from apps.orchestrator.runtime import Edge, MultiWorkflowRuntimeService, Node, Workflow
from apps.orchestrator.runtime.env import get_env
from apps.orchestrator.runtime.models import Event as RuntimeEvent
from apps.orchestrator.runtime.projection import (
    OUTPUT_INCLUDE_PATHS_KEY,
    STATE_EXCLUDE_PATHS_KEY,
    normalize_projection_paths,
)
from apps.orchestrator.streaming.sse import _event_stream
from apps.orchestrator.workflow_engine_adapter import WorkflowEngineAdapter, WorkflowEngineAdapterError
from apps.orchestrator.webhooks.service import WebhookService

_ROOT_DIR = Path(__file__).resolve().parents[3]
_OPENAPI_SPEC_PATH = _ROOT_DIR / "docs" / "api" / "openapi.yaml"
_API_REFERENCE_PATH = _ROOT_DIR / "docs" / "api" / "reference.md"
_WORKFLOW_AUTHORING_GUIDE_PATH = _ROOT_DIR / "docs" / "architecture" / "workflow-authoring-agents.md"
_WORKFLOW_DRAFT_SCHEMA_PATH = _ROOT_DIR / "docs" / "api" / "schemas" / "workflow-draft.schema.json"
_WORKFLOW_EXPORT_SCHEMA_PATH = _ROOT_DIR / "docs" / "api" / "schemas" / "workflow-export-v1.schema.json"
_ROUTING_DECISION_SCHEMA_PATH = _ROOT_DIR / "docs" / "api" / "schemas" / "routing-decision.schema.json"
_AGENT_INTEGRATION_LOGGER = logging.getLogger("workcore.agent_integration")
_DEFAULT_AGENT_INTEGRATION_LOG_LIMIT = 100
_MAX_AGENT_INTEGRATION_LOG_LIMIT = 500
_DEFAULT_AGENT_INTEGRATION_LOG_CAPACITY = 1000
_RUN_LEDGER_FK_CONSTRAINT = "run_ledger_run_id_fkey"
_RUN_LEDGER_FK_MAX_ATTEMPTS = 4
_RUN_LEDGER_FK_RETRY_BASE_DELAY_SECONDS = 0.02


class RunLedgerWriteRaceError(RuntimeError):
    incident_code = "RUN_LEDGER_RUN_NOT_VISIBLE"

    def __init__(self, run_id: str, attempts: int) -> None:
        super().__init__("run ledger write blocked: run row not visible after retry window")
        self.run_id = run_id
        self.attempts = attempts


def _iter_exception_chain(exc: BaseException):
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        cause = current.__cause__
        if isinstance(cause, BaseException):
            current = cause
            continue
        context = current.__context__
        if isinstance(context, BaseException):
            current = context
            continue
        current = None


def _is_run_ledger_fk_violation(exc: BaseException) -> bool:
    for candidate in _iter_exception_chain(exc):
        text = str(candidate)
        normalized = text.lower()
        if _RUN_LEDGER_FK_CONSTRAINT in normalized:
            return True
        if (
            "foreign key constraint" in normalized
            and "run_ledger" in normalized
            and "(run_id)" in normalized
            and 'table "runs"' in normalized
        ):
            return True
        class_name = candidate.__class__.__name__.lower()
        if "foreignkeyviolation" in class_name and "run_ledger" in normalized:
            return True
    return False


def _workflow_engine_error_details(exc: BaseException) -> Optional[Dict[str, Any]]:
    details: Dict[str, Any] = {}
    incident_code = getattr(exc, "incident_code", None)
    if isinstance(incident_code, str) and incident_code:
        details["incident_code"] = incident_code
    run_id = getattr(exc, "run_id", None)
    if isinstance(run_id, str) and run_id:
        details["run_id"] = run_id
    attempts = getattr(exc, "attempts", None)
    if isinstance(attempts, int) and attempts > 0:
        details["attempts"] = attempts
    return details or None


def _is_truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def validate_runtime_security_env() -> None:
    if _is_truthy(get_env("WORKCORE_ALLOW_INSECURE_DEV", "0")):
        return

    required = (
        "WORKCORE_API_AUTH_TOKEN",
        "WEBHOOK_DEFAULT_INBOUND_SECRET",
        "CORS_ALLOW_ORIGINS",
        "INTEGRATION_HTTP_ALLOWED_HOSTS",
    )
    for name in required:
        if not (get_env(name) or "").strip():
            raise RuntimeError(
                f"{name} is required for secure startup; "
                "set WORKCORE_ALLOW_INSECURE_DEV=1 only for temporary local troubleshooting"
            )

    cors_allow_origins = get_env("CORS_ALLOW_ORIGINS", "") or ""
    if "*" in cors_allow_origins:
        raise RuntimeError(
            "CORS_ALLOW_ORIGINS must not contain '*' for secure startup; "
            "set explicit origins or use WORKCORE_ALLOW_INSECURE_DEV=1 temporarily"
        )

    allowed_hosts = get_env("INTEGRATION_HTTP_ALLOWED_HOSTS", "") or ""
    host_rules = [item.strip() for item in allowed_hosts.split(",") if item.strip()]
    if any(rule == "*" for rule in host_rules):
        raise RuntimeError(
            "INTEGRATION_HTTP_ALLOWED_HOSTS must not contain bare '*' for secure startup; "
            "use explicit hostnames or wildcard subdomains (for example '*.example.com')"
        )

    deny_cidrs_raw = get_env("INTEGRATION_HTTP_DENY_CIDRS", "") or ""
    for raw_item in deny_cidrs_raw.split(","):
        item = raw_item.strip()
        if not item:
            continue
        try:
            ipaddress.ip_network(item, strict=False)
        except ValueError as exc:
            raise RuntimeError(
                f"INTEGRATION_HTTP_DENY_CIDRS contains invalid CIDR value '{item}'"
            ) from exc


class ApiContext:
    def __init__(
        self,
        run_store: Optional[Any] = None,
        workflow_store=None,
        artifact_store=None,
        runtime: Optional[MultiWorkflowRuntimeService] = None,
        orchestration_store: Optional[Any] = None,
        default_inbound_secret: Optional[str] = None,
        default_integration_key: str = "default",
    ) -> None:
        self.run_store = run_store
        self.workflow_store = workflow_store
        self.artifact_store = artifact_store
        self.runtime = runtime
        self.orchestration_store = orchestration_store
        self.idempotency: Optional[IdempotencyStore] = None
        self.capability_store: Optional[Any] = None
        self.run_ledger_store: Optional[Any] = None
        self.handoff_store: Optional[Any] = None
        self.project_router: Optional[ProjectRouter] = None
        self.workflow_engine_adapter: Optional[WorkflowEngineAdapter] = None
        self.project_orchestrator: Optional[ProjectOrchestratorRuntime] = None
        self._workflow_store_owned = False
        self._run_store_owned = False
        self._artifact_store_owned = False
        self._idempotency_owned = False
        self._capability_store_owned = False
        self._run_ledger_store_owned = False
        self._handoff_store_owned = False
        self._orchestration_store_owned = False
        self._runtime_started = False
        self.webhooks = WebhookService.create()
        if default_inbound_secret:
            self.webhooks.register_inbound_key(default_integration_key, default_inbound_secret)
        if self.runtime:
            self.runtime.event_hook = self._handle_runtime_events
            self.runtime.resolve_capability = self._resolve_capability

    async def ensure_workflow_store(self) -> None:
        if self.workflow_store is None:
            self.workflow_store = await create_workflow_store()
            self._workflow_store_owned = True

    async def ensure_run_store(self) -> None:
        if self.run_store is None:
            await self.ensure_workflow_store()
            self.run_store = await create_run_store(self.workflow_store)
            self._run_store_owned = True

    async def ensure_artifact_store(self) -> None:
        if self.artifact_store is None:
            self.artifact_store = await create_artifact_store()
            self._artifact_store_owned = True

    async def ensure_idempotency(self) -> None:
        if self.idempotency is None:
            await self.ensure_workflow_store()
            self.idempotency = await create_idempotency_store(self.workflow_store)
            self._idempotency_owned = True

    async def ensure_capability_store(self) -> None:
        if self.capability_store is None:
            await self.ensure_workflow_store()
            self.capability_store = await create_capability_store(self.workflow_store)
            self._capability_store_owned = True

    async def ensure_run_ledger_store(self) -> None:
        if self.run_ledger_store is None:
            await self.ensure_workflow_store()
            self.run_ledger_store = await create_run_ledger_store(self.workflow_store)
            self._run_ledger_store_owned = True

    async def ensure_handoff_store(self) -> None:
        if self.handoff_store is None:
            await self.ensure_workflow_store()
            self.handoff_store = await create_handoff_store(self.workflow_store)
            self._handoff_store_owned = True

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

            executor_mode = (get_env("AGENT_EXECUTOR_MODE") or "").strip().lower()
            integration_http_policy = IntegrationHTTPEgressPolicy.from_env(get_env)
            executors: Dict[str, Any] = {
                "agent_mock": MockAgentExecutor(),
                "integration_http": IntegrationHTTPExecutor(egress_policy=integration_http_policy),
            }
            if AGENTS_AVAILABLE:
                executors["agent_live"] = AgentExecutor()

            if executor_mode == "mock":
                executors["agent"] = executors["agent_mock"]
            elif executor_mode == "live":
                if executors.get("agent_live"):
                    executors["agent"] = executors["agent_live"]
            elif executors.get("agent_live"):
                executors["agent"] = executors["agent_live"]

            self.runtime = MultiWorkflowRuntimeService.create(
                loader,
                executors=executors,
                resolve_capability=self._resolve_capability,
            )
            self.runtime.event_hook = self._handle_runtime_events

    async def ensure_orchestration(self) -> None:
        if self.orchestration_store is None:
            await self.ensure_workflow_store()
            self.orchestration_store = await create_orchestration_store(self.workflow_store)
            self._orchestration_store_owned = True
        if self.workflow_engine_adapter is None:
            await self.ensure_runtime()
            await self.ensure_run_store()
            self.workflow_engine_adapter = WorkflowEngineAdapter(self.runtime, self.run_store)
        if self.project_router is None:
            self.project_router = ProjectRouter(self.orchestration_store)
        if self.project_orchestrator is None:
            self.project_orchestrator = ProjectOrchestratorRuntime(
                self.orchestration_store,
                self.workflow_engine_adapter,
            )

    async def close(self) -> None:
        await self.webhooks.stop_background_dispatcher()
        if self._idempotency_owned and self.idempotency:
            await self.idempotency.close()
        if self._capability_store_owned and self.capability_store:
            close_result = self.capability_store.close()
            if isawaitable(close_result):
                await close_result
        if self._run_ledger_store_owned and self.run_ledger_store:
            close_result = self.run_ledger_store.close()
            if isawaitable(close_result):
                await close_result
        if self._handoff_store_owned and self.handoff_store:
            close_result = self.handoff_store.close()
            if isawaitable(close_result):
                await close_result
        if self._orchestration_store_owned and self.orchestration_store:
            close_result = self.orchestration_store.close()
            if isawaitable(close_result):
                await close_result
        if self._run_store_owned and self.run_store:
            close_result = self.run_store.close()
            if isawaitable(close_result):
                await close_result
        if self._artifact_store_owned and self.artifact_store:
            close_result = self.artifact_store.close()
            if isawaitable(close_result):
                await close_result
        if self._workflow_store_owned and self.workflow_store:
            await self.workflow_store.close()
        if self.runtime and self._runtime_started:
            await self.runtime.shutdown()

    async def _resolve_capability(self, tenant_id: str, capability_id: str, version: str) -> Optional[Dict[str, Any]]:
        await self.ensure_capability_store()
        if self.capability_store is None:
            return None
        record = await self.capability_store.get(capability_id, version, tenant_id=tenant_id)
        if not record:
            return None
        return {
            "capability_id": record.capability_id,
            "version": record.version,
            "node_type": record.node_type,
            "contract": record.contract,
            **(record.contract or {}),
        }

    @staticmethod
    def _run_tenant_id(run: Any) -> str:
        metadata = run.metadata if isinstance(getattr(run, "metadata", None), dict) else {}
        tenant = metadata.get("tenant_id")
        if isinstance(tenant, str) and tenant:
            return tenant
        return "local"

    async def _persist_run(self, run: Any) -> None:
        await self.ensure_run_store()
        if self.run_store is None:
            return
        saved = self.run_store.save(run, tenant_id=self._run_tenant_id(run))
        if isawaitable(saved):
            await saved

    async def _append_run_ledger_entries_with_retry(self, run: Any, entries: list[Any]) -> None:
        if self.run_ledger_store is None or not entries:
            return
        run_id_raw = getattr(run, "id", None)
        run_id = run_id_raw if isinstance(run_id_raw, str) and run_id_raw else "run_unknown"
        for attempt in range(1, _RUN_LEDGER_FK_MAX_ATTEMPTS + 1):
            try:
                await self.run_ledger_store.append_entries(entries)
                return
            except Exception as exc:
                fk_violation = _is_run_ledger_fk_violation(exc)
                if fk_violation and attempt < _RUN_LEDGER_FK_MAX_ATTEMPTS:
                    await self._persist_run(run)
                    await asyncio.sleep(_RUN_LEDGER_FK_RETRY_BASE_DELAY_SECONDS * attempt)
                    continue
                if fk_violation:
                    raise RunLedgerWriteRaceError(run_id=run_id, attempts=attempt) from exc
                raise

    async def _handle_runtime_events(self, run, events) -> None:
        await self._persist_run(run)
        await self.webhooks.handle_events(run, events)
        await self.ensure_run_ledger_store()
        if self.run_ledger_store is None:
            return
        entries = runtime_events_to_ledger_entries(run, events)
        if not entries:
            return
        await self._append_run_ledger_entries_with_retry(run, entries)


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
    project_id: Optional[str] = None,
) -> Workflow:
    workflow = await store.get_workflow(workflow_id, tenant_id=tenant_id, project_id=project_id)
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
    artifact_store: Optional[Any] = None,
    runtime: Optional[MultiWorkflowRuntimeService] = None,
    orchestration_store: Optional[Any] = None,
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
        artifact_store=artifact_store,
        runtime=runtime,
        orchestration_store=orchestration_store,
        default_inbound_secret=inbound_secret,
        default_integration_key=integration_key,
    )
    app: Starlette | None = None
    capacity_raw = get_env("AGENT_INTEGRATION_LOG_CAPACITY", str(_DEFAULT_AGENT_INTEGRATION_LOG_CAPACITY))
    try:
        log_capacity = int(capacity_raw or _DEFAULT_AGENT_INTEGRATION_LOG_CAPACITY)
    except ValueError:
        log_capacity = _DEFAULT_AGENT_INTEGRATION_LOG_CAPACITY
    log_capacity = max(_MAX_AGENT_INTEGRATION_LOG_LIMIT, min(log_capacity, 5000))
    integration_logs: deque[Dict[str, Any]] = deque(maxlen=log_capacity)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        await ctx.ensure_workflow_store()
        await ctx.ensure_run_store()
        await ctx.ensure_artifact_store()
        await ctx.ensure_idempotency()
        await ctx.ensure_runtime()
        await ctx.ensure_orchestration()
        await ctx.runtime.startup()
        await ctx.webhooks.start_background_dispatcher()
        ctx._runtime_started = True
        app.state.runtime = ctx.runtime
        app.state.run_store = ctx.run_store
        app.state.workflow_store = ctx.workflow_store
        app.state.artifact_store = ctx.artifact_store
        app.state.orchestration_store = ctx.orchestration_store
        app.state.project_router = ctx.project_router
        app.state.project_orchestrator = ctx.project_orchestrator
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

    def _project_id(request: Request) -> Optional[str]:
        existing = getattr(request.state, "project_id", None)
        if isinstance(existing, str) and existing.strip():
            return existing.strip()
        incoming = request.headers.get("X-Project-Id")
        if not incoming:
            return None
        project_id = incoming.strip()
        if not project_id:
            return None
        request.state.project_id = project_id
        return project_id

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

    def _projection_error_code(exc: ValueError) -> str:
        return "projection.path_invalid" if "not a valid path" in str(exc) else "INVALID_ARGUMENT"

    def _version_projection_defaults(version_content: Any) -> tuple[list[str], list[str]]:
        defaults = no_inline_projection_defaults(version_content if isinstance(version_content, dict) else {})
        if not defaults:
            return [], []
        state_paths: list[str] = []
        output_paths: list[str] = []
        try:
            state_paths = normalize_projection_paths(defaults.get(STATE_EXCLUDE_PATHS_KEY), field_name=STATE_EXCLUDE_PATHS_KEY)
        except ValueError:
            state_paths = []
        try:
            output_paths = normalize_projection_paths(
                defaults.get(OUTPUT_INCLUDE_PATHS_KEY),
                field_name=OUTPUT_INCLUDE_PATHS_KEY,
            )
        except ValueError:
            output_paths = []
        return state_paths, output_paths

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
        details: Optional[Any] = None,
    ) -> JSONResponse:
        error: Dict[str, Any] = {"code": code, "message": message}
        if details is not None:
            error["details"] = details
        return JSONResponse(
            {"error": error, "correlation_id": _correlation_id(request)},
            status_code=status_code,
        )

    def _truncate_text(value: Any, max_len: int = 600) -> str:
        text = str(value)
        if len(text) <= max_len:
            return text
        return f"{text[: max_len - 3]}..."

    def _sanitize_log_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(context, dict):
            return {}
        sanitized: Dict[str, Any] = {}
        for key, value in context.items():
            if value is None:
                continue
            if isinstance(value, (bool, int, float)):
                sanitized[key] = value
            elif isinstance(value, str):
                sanitized[key] = _truncate_text(value)
            elif isinstance(value, dict):
                sanitized[key] = f"<dict keys={len(value)}>"
            elif isinstance(value, (list, tuple, set)):
                sanitized[key] = f"<{type(value).__name__} size={len(value)}>"
            else:
                sanitized[key] = f"<{type(value).__name__}>"
        return sanitized

    def _integration_log(
        request: Request,
        event: str,
        detail: str,
        *,
        level: str = "INFO",
        status_code: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        level_name = level.upper()
        if level_name not in {"INFO", "WARNING", "ERROR"}:
            level_name = "INFO"
        safe_context = _sanitize_log_context(context)
        entry = {
            "log_id": f"ilog_{uuid.uuid4().hex[:12]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level_name,
            "event": event,
            "detail": _truncate_text(detail),
            "http_method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "correlation_id": _correlation_id(request),
            "trace_id": _trace_id(request),
            "tenant_id": _tenant_id(request),
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("User-Agent"),
            "context": safe_context,
        }
        integration_logs.append(entry)
        line = json.dumps(
            {
                "event": entry["event"],
                "log_id": entry["log_id"],
                "correlation_id": entry["correlation_id"],
                "trace_id": entry["trace_id"],
                "status_code": entry["status_code"],
                "context": safe_context,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        if level_name == "ERROR":
            _AGENT_INTEGRATION_LOGGER.error(line)
        elif level_name == "WARNING":
            _AGENT_INTEGRATION_LOGGER.warning(line)
        else:
            _AGENT_INTEGRATION_LOGGER.info(line)
        return entry

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
            try:
                await ctx.idempotency.set(key, scope, response.status_code, payload, tenant_id=tenant)
            except Exception as exc:
                _integration_log(
                    request,
                    "idempotency.cache_write_failed",
                    str(exc),
                    level="WARNING",
                    status_code=response.status_code,
                    context={"scope": scope, "exception_type": exc.__class__.__name__},
                )
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
            node_config = node.get("config", {})
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
            if node_type == "set_state":
                if node_config is None:
                    node_config = {}
                if not isinstance(node_config, dict):
                    errors.append(f"draft.nodes[{idx}].config must be an object for set_state")
                    continue

                assignments_raw = node_config.get("assignments")
                if assignments_raw is not None:
                    if not isinstance(assignments_raw, list) or not assignments_raw:
                        errors.append(f"draft.nodes[{idx}].config.assignments must be a non-empty array")
                    else:
                        for assignment_index, assignment in enumerate(assignments_raw):
                            if not isinstance(assignment, dict):
                                errors.append(
                                    f"draft.nodes[{idx}].config.assignments[{assignment_index}] must be an object"
                                )
                                continue
                            target = assignment.get("target")
                            expression = assignment.get("expression")
                            if not isinstance(target, str) or not target.strip():
                                errors.append(
                                    f"draft.nodes[{idx}].config.assignments[{assignment_index}].target is required"
                                )
                            if not isinstance(expression, str) or not expression.strip():
                                errors.append(
                                    f"draft.nodes[{idx}].config.assignments[{assignment_index}].expression is required"
                                )
                else:
                    target = node_config.get("target")
                    expression = node_config.get("expression")
                    if not isinstance(target, str) or not target.strip() or not isinstance(expression, str) or not expression.strip():
                        errors.append(
                            f"draft.nodes[{idx}] set_state requires target+expression or non-empty assignments[]"
                        )
            if node_type == "integration_http":
                if node_config is None:
                    node_config = {}
                if not isinstance(node_config, dict):
                    errors.append(f"draft.nodes[{idx}].config must be an object for integration_http")
                    continue
                url = node_config.get("url")
                if not isinstance(url, str) or not url.strip():
                    errors.append(f"draft.nodes[{idx}].config.url is required for integration_http")
                method = node_config.get("method")
                if method is not None:
                    if not isinstance(method, str) or method.strip().upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                        errors.append(
                            f"draft.nodes[{idx}].config.method must be one of GET, POST, PUT, PATCH, DELETE"
                        )

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

    async def _validate_capability_refs(draft: Dict[str, Any], tenant_id: str) -> list[str]:
        errors: list[str] = []
        nodes_raw = draft.get("nodes")
        if not isinstance(nodes_raw, list):
            return errors
        await ctx.ensure_capability_store()
        if ctx.capability_store is None:
            return errors
        for idx, node in enumerate(nodes_raw):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or f"node_{idx}")
            config = node.get("config")
            if config is None:
                config = {}
            if not isinstance(config, dict):
                continue
            cap_id_raw = config.get("capability_id")
            cap_version_raw = config.get("capability_version")
            cap_id = cap_id_raw.strip() if isinstance(cap_id_raw, str) else ""
            cap_version = cap_version_raw.strip() if isinstance(cap_version_raw, str) else ""
            if bool(cap_id) != bool(cap_version):
                errors.append(f"node {node_id} requires both capability_id and capability_version")
                continue
            if not cap_id:
                continue
            record = await ctx.capability_store.get(cap_id, cap_version, tenant_id=tenant_id)
            if record is None:
                errors.append(f"node {node_id} references unknown capability {cap_id}@{cap_version}")
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

    async def _require_orchestration() -> ProjectOrchestratorRuntime:
        await _require_runtime()
        await ctx.ensure_orchestration()
        if app is not None:
            app.state.orchestration_store = ctx.orchestration_store
            app.state.project_router = ctx.project_router
            app.state.project_orchestrator = ctx.project_orchestrator
        if ctx.project_orchestrator is None:
            raise RuntimeError("orchestrator runtime is not initialized")
        return ctx.project_orchestrator

    async def create_project(request: Request) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)
        project_id_raw = payload.get("project_id")
        if not isinstance(project_id_raw, str) or not project_id_raw.strip():
            return _error(request, "INVALID_ARGUMENT", "project_id is required", 400)
        project_name_raw = payload.get("project_name")
        if not isinstance(project_name_raw, str) or not project_name_raw.strip():
            return _error(request, "INVALID_ARGUMENT", "project_name is required", 400)
        default_orchestrator_id_raw = payload.get("default_orchestrator_id")
        if default_orchestrator_id_raw is not None and (
            not isinstance(default_orchestrator_id_raw, str) or not default_orchestrator_id_raw.strip()
        ):
            return _error(
                request,
                "INVALID_ARGUMENT",
                "default_orchestrator_id must be a non-empty string or null",
                400,
            )
        settings = payload.get("settings")
        if settings is None:
            settings = {}
        if not isinstance(settings, dict):
            return _error(request, "INVALID_ARGUMENT", "settings must be an object", 400)

        await ctx.ensure_orchestration()
        if ctx.orchestration_store is None:
            return _error(request, "INTERNAL", "orchestration store is unavailable", 500)

        try:
            project = await ctx.orchestration_store.create_project(
                project_id=project_id_raw.strip(),
                tenant_id=_tenant_id(request),
                project_name=project_name_raw.strip(),
                default_orchestrator_id=(
                    default_orchestrator_id_raw.strip()
                    if isinstance(default_orchestrator_id_raw, str)
                    else None
                ),
                settings=settings,
            )
        except ProjectConflictError:
            return _error(request, "CONFLICT", "project already exists", 409)

        return _json(request, project_to_dict(project), status_code=201)

    async def list_projects(request: Request) -> JSONResponse:
        limit_raw = request.query_params.get("limit")
        limit = 50
        if limit_raw:
            try:
                limit = max(1, min(200, int(limit_raw)))
            except ValueError:
                return _error(request, "INVALID_ARGUMENT", "limit must be an integer", 400)

        await ctx.ensure_orchestration()
        if ctx.orchestration_store is None:
            return _error(request, "INTERNAL", "orchestration store is unavailable", 500)

        projects = await ctx.orchestration_store.list_projects(tenant_id=_tenant_id(request), limit=limit)
        return _json(
            request,
            {"items": [project_to_dict(project) for project in projects], "next_cursor": None},
        )

    async def update_project(request: Request) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)
        project_id = str(request.path_params.get("project_id") or "").strip()
        if not project_id:
            return _error(request, "ERR_PROJECT_ID_REQUIRED", "project_id is required", 422)
        project_name_raw = payload.get("project_name")
        if not isinstance(project_name_raw, str) or not project_name_raw.strip():
            return _error(request, "INVALID_ARGUMENT", "project_name is required", 400)

        await ctx.ensure_orchestration()
        if ctx.orchestration_store is None:
            return _error(request, "INTERNAL", "orchestration store is unavailable", 500)

        tenant = _tenant_id(request)
        project = await ctx.orchestration_store.update_project(
            project_id=project_id,
            tenant_id=tenant,
            project_name=project_name_raw.strip(),
        )
        if project is None:
            return _error(request, "ERR_PROJECT_NOT_FOUND", "project not found", 404)
        return _json(request, project_to_dict(project))

    async def delete_project(request: Request) -> Response:
        project_id = str(request.path_params.get("project_id") or "").strip()
        if not project_id:
            return _error(request, "ERR_PROJECT_ID_REQUIRED", "project_id is required", 422)

        await ctx.ensure_orchestration()
        if ctx.orchestration_store is None:
            return _error(request, "INTERNAL", "orchestration store is unavailable", 500)

        await ctx.ensure_workflow_store()
        if ctx.workflow_store is None:
            return _error(request, "INTERNAL", "workflow store is unavailable", 500)

        tenant = _tenant_id(request)
        project = await ctx.orchestration_store.get_project(project_id, tenant_id=tenant)
        if project is None:
            return _error(request, "ERR_PROJECT_NOT_FOUND", "project not found", 404)

        workflows = await ctx.workflow_store.list_workflows(
            limit=1,
            tenant_id=tenant,
            project_id=project_id,
        )
        if workflows:
            return _error(request, "ERR_PROJECT_NOT_EMPTY", "project has workflows", 409)

        deleted = await ctx.orchestration_store.delete_project(project_id=project_id, tenant_id=tenant)
        if not deleted:
            return _error(request, "ERR_PROJECT_NOT_FOUND", "project not found", 404)
        return Response(status_code=204)

    def _require_string_list(payload: Dict[str, Any], field: str) -> list[str]:
        raw = payload.get(field)
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ValueError(f"{field} must be an array of strings")
        values: list[str] = []
        for index, item in enumerate(raw):
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"{field}[{index}] must be a non-empty string")
            values.append(item.strip())
        return values

    async def upsert_project_orchestrator(request: Request) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)

        project_id = str(request.path_params.get("project_id") or "").strip()
        if not project_id:
            return _error(request, "ERR_PROJECT_ID_REQUIRED", "project_id is required", 422)
        orchestrator_id_raw = payload.get("orchestrator_id")
        if not isinstance(orchestrator_id_raw, str) or not orchestrator_id_raw.strip():
            return _error(request, "INVALID_ARGUMENT", "orchestrator_id is required", 400)
        name_raw = payload.get("name")
        if not isinstance(name_raw, str) or not name_raw.strip():
            return _error(request, "INVALID_ARGUMENT", "name is required", 400)
        routing_policy_raw = payload.get("routing_policy")
        if routing_policy_raw is None:
            routing_policy = {}
        elif isinstance(routing_policy_raw, dict):
            routing_policy = dict(routing_policy_raw)
        else:
            return _error(request, "INVALID_ARGUMENT", "routing_policy must be an object", 400)

        fallback_workflow_id_raw = payload.get("fallback_workflow_id")
        if fallback_workflow_id_raw is not None and (
            not isinstance(fallback_workflow_id_raw, str) or not fallback_workflow_id_raw.strip()
        ):
            return _error(
                request,
                "INVALID_ARGUMENT",
                "fallback_workflow_id must be a non-empty string or null",
                400,
            )
        fallback_workflow_id = fallback_workflow_id_raw.strip() if isinstance(fallback_workflow_id_raw, str) else None

        prompt_profile_raw = payload.get("prompt_profile")
        if prompt_profile_raw is not None and (not isinstance(prompt_profile_raw, str) or not prompt_profile_raw.strip()):
            return _error(
                request,
                "INVALID_ARGUMENT",
                "prompt_profile must be a non-empty string or null",
                400,
            )
        prompt_profile = prompt_profile_raw.strip() if isinstance(prompt_profile_raw, str) else None

        set_as_default_raw = payload.get("set_as_default", False)
        if not isinstance(set_as_default_raw, bool):
            return _error(request, "INVALID_ARGUMENT", "set_as_default must be a boolean", 400)
        set_as_default = bool(set_as_default_raw)

        await ctx.ensure_orchestration()
        if ctx.orchestration_store is None:
            return _error(request, "INTERNAL", "orchestration store is unavailable", 500)

        tenant = _tenant_id(request)
        project = await ctx.orchestration_store.get_project(project_id, tenant_id=tenant)
        if project is None:
            return _error(request, "ERR_PROJECT_NOT_FOUND", "project not found", 404)

        if fallback_workflow_id:
            try:
                await ctx.workflow_store.get_workflow(
                    fallback_workflow_id,
                    tenant_id=tenant,
                    project_id=project_id,
                )
            except WorkflowNotFoundError:
                return _error(request, "ERR_WORKFLOW_NOT_IN_PROJECT", "workflow is not registered in project", 409)

        config = await ctx.orchestration_store.upsert_orchestrator_config(
            project_id=project.project_id,
            orchestrator_id=orchestrator_id_raw.strip(),
            name=name_raw.strip(),
            tenant_id=tenant,
            routing_policy=routing_policy,
            fallback_workflow_id=fallback_workflow_id,
            prompt_profile=prompt_profile,
            set_as_default=set_as_default,
        )
        return _json(request, orchestrator_config_to_dict(config), status_code=201)

    async def upsert_project_workflow_definition(request: Request) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)

        project_id = str(request.path_params.get("project_id") or "").strip()
        if not project_id:
            return _error(request, "ERR_PROJECT_ID_REQUIRED", "project_id is required", 422)
        workflow_id_raw = payload.get("workflow_id")
        if not isinstance(workflow_id_raw, str) or not workflow_id_raw.strip():
            return _error(request, "INVALID_ARGUMENT", "workflow_id is required", 400)
        name_raw = payload.get("name")
        if not isinstance(name_raw, str) or not name_raw.strip():
            return _error(request, "INVALID_ARGUMENT", "name is required", 400)
        description_raw = payload.get("description")
        if not isinstance(description_raw, str) or not description_raw.strip():
            return _error(request, "INVALID_ARGUMENT", "description is required", 400)

        try:
            tags = _require_string_list(payload, "tags")
            examples = _require_string_list(payload, "examples")
        except ValueError as exc:
            return _error(request, "INVALID_ARGUMENT", str(exc), 400)

        active_raw = payload.get("active", True)
        if not isinstance(active_raw, bool):
            return _error(request, "INVALID_ARGUMENT", "active must be a boolean", 400)
        is_fallback_raw = payload.get("is_fallback", False)
        if not isinstance(is_fallback_raw, bool):
            return _error(request, "INVALID_ARGUMENT", "is_fallback must be a boolean", 400)

        await ctx.ensure_orchestration()
        if ctx.orchestration_store is None:
            return _error(request, "INTERNAL", "orchestration store is unavailable", 500)

        tenant = _tenant_id(request)
        project = await ctx.orchestration_store.get_project(project_id, tenant_id=tenant)
        if project is None:
            return _error(request, "ERR_PROJECT_NOT_FOUND", "project not found", 404)

        workflow_id = workflow_id_raw.strip()
        try:
            await ctx.workflow_store.get_workflow(
                workflow_id,
                tenant_id=tenant,
                project_id=project_id,
            )
        except WorkflowNotFoundError:
            return _error(request, "ERR_WORKFLOW_NOT_IN_PROJECT", "workflow is not registered in project", 409)

        definition = await ctx.orchestration_store.upsert_workflow_definition(
            project_id=project.project_id,
            workflow_id=workflow_id,
            tenant_id=tenant,
            name=name_raw.strip(),
            description=description_raw.strip(),
            tags=tags,
            examples=examples,
            active=active_raw,
            is_fallback=is_fallback_raw,
        )
        return _json(request, workflow_definition_to_dict(definition), status_code=201)

    async def create_capability(request: Request) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)
        capability_id = payload.get("capability_id")
        version = payload.get("version")
        node_type = payload.get("node_type")
        contract = payload.get("contract")
        if not isinstance(capability_id, str) or not capability_id.strip():
            return _error(request, "INVALID_ARGUMENT", "capability_id is required", 400)
        if not isinstance(version, str) or not version.strip():
            return _error(request, "INVALID_ARGUMENT", "version is required", 400)
        if not isinstance(node_type, str) or not node_type.strip():
            return _error(request, "INVALID_ARGUMENT", "node_type is required", 400)
        if not isinstance(contract, dict):
            return _error(request, "INVALID_ARGUMENT", "contract must be an object", 400)
        await ctx.ensure_capability_store()
        if ctx.capability_store is None:
            return _error(request, "INTERNAL", "capability store unavailable", 500)
        try:
            record = await ctx.capability_store.create(
                capability_id=capability_id.strip(),
                version=version.strip(),
                node_type=node_type.strip(),
                contract=contract,
                tenant_id=_tenant_id(request),
            )
        except CapabilityConflictError:
            return _error(request, "CONFLICT", "capability version already exists", 409)
        return _json(request, capability_to_dict(record), status_code=201)

    async def list_capabilities(request: Request) -> JSONResponse:
        capability_id = request.query_params.get("capability_id")
        limit_raw = request.query_params.get("limit", "200")
        try:
            limit = int(limit_raw)
        except ValueError:
            return _error(request, "INVALID_ARGUMENT", "limit must be an integer", 400)
        if limit < 1 or limit > 1000:
            return _error(request, "INVALID_ARGUMENT", "limit must be between 1 and 1000", 400)
        await ctx.ensure_capability_store()
        if ctx.capability_store is None:
            return _error(request, "INTERNAL", "capability store unavailable", 500)
        items = await ctx.capability_store.list_capabilities(
            tenant_id=_tenant_id(request),
            capability_id=capability_id.strip() if isinstance(capability_id, str) and capability_id.strip() else None,
            limit=limit,
        )
        return _json(request, {"items": [capability_to_dict(item) for item in items], "next_cursor": None})

    async def list_capability_versions(request: Request) -> JSONResponse:
        capability_id = str(request.path_params.get("capability_id") or "").strip()
        if not capability_id:
            return _error(request, "INVALID_ARGUMENT", "capability_id is required", 400)
        limit_raw = request.query_params.get("limit", "200")
        try:
            limit = int(limit_raw)
        except ValueError:
            return _error(request, "INVALID_ARGUMENT", "limit must be an integer", 400)
        if limit < 1 or limit > 1000:
            return _error(request, "INVALID_ARGUMENT", "limit must be between 1 and 1000", 400)
        await ctx.ensure_capability_store()
        if ctx.capability_store is None:
            return _error(request, "INTERNAL", "capability store unavailable", 500)
        items = await ctx.capability_store.list_versions(
            capability_id=capability_id,
            tenant_id=_tenant_id(request),
            limit=limit,
        )
        return _json(request, {"items": [capability_to_dict(item) for item in items], "next_cursor": None})

    async def create_workflow(request: Request) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)
        project_id = _project_id(request)
        if not project_id:
            return _error(request, "ERR_PROJECT_ID_REQUIRED", "X-Project-Id header is required", 422)
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
            project_id=project_id,
        )
        return _json(request, workflow_to_dict(workflow), status_code=201)

    async def list_workflows(request: Request) -> JSONResponse:
        project_id = _project_id(request)
        if not project_id:
            return _error(request, "ERR_PROJECT_ID_REQUIRED", "X-Project-Id header is required", 422)
        limit_raw = request.query_params.get("limit")
        limit = 50
        if limit_raw:
            try:
                limit = max(1, min(200, int(limit_raw)))
            except ValueError:
                return _error(request, "INVALID_ARGUMENT", "limit must be an integer", 400)
        workflows = await ctx.workflow_store.list_workflows(
            limit=limit,
            tenant_id=_tenant_id(request),
            project_id=project_id,
        )
        return _json(
            request,
            {"items": [workflow_summary_to_dict(item) for item in workflows], "next_cursor": None}
        )

    async def update_workflow(request: Request) -> JSONResponse:
        project_id = _project_id(request)
        if not project_id:
            return _error(request, "ERR_PROJECT_ID_REQUIRED", "X-Project-Id header is required", 422)
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
                project_id=project_id,
            )
        except WorkflowNotFoundError:
            return _error(request, "NOT_FOUND", "workflow not found", 404)
        return _json(request, workflow_to_dict(workflow))

    async def get_workflow(request: Request) -> JSONResponse:
        project_id = _project_id(request)
        if not project_id:
            return _error(request, "ERR_PROJECT_ID_REQUIRED", "X-Project-Id header is required", 422)
        workflow_id = request.path_params["workflow_id"]
        try:
            workflow = await ctx.workflow_store.get_workflow(
                workflow_id,
                tenant_id=_tenant_id(request),
                project_id=project_id,
            )
        except WorkflowNotFoundError:
            return _error(request, "NOT_FOUND", "workflow not found", 404)
        return _json(request, workflow_to_dict(workflow))

    async def delete_workflow(request: Request) -> Response:
        project_id = _project_id(request)
        if not project_id:
            return _error(request, "ERR_PROJECT_ID_REQUIRED", "X-Project-Id header is required", 422)
        workflow_id = request.path_params["workflow_id"]
        try:
            await ctx.workflow_store.delete_workflow(
                workflow_id,
                tenant_id=_tenant_id(request),
                project_id=project_id,
            )
        except WorkflowNotFoundError:
            return _error(request, "NOT_FOUND", "workflow not found", 404)
        return Response(status_code=204)

    async def update_workflow_draft(request: Request) -> JSONResponse:
        project_id = _project_id(request)
        if not project_id:
            return _error(request, "ERR_PROJECT_ID_REQUIRED", "X-Project-Id header is required", 422)
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
            workflow = await ctx.workflow_store.update_draft(
                workflow_id,
                draft,
                tenant_id=_tenant_id(request),
                project_id=project_id,
            )
        except WorkflowNotFoundError:
            return _error(request, "NOT_FOUND", "workflow not found", 404)
        return _json(request, workflow_to_dict(workflow))

    async def publish_workflow(request: Request) -> JSONResponse:
        project_id = _project_id(request)
        if not project_id:
            return _error(request, "ERR_PROJECT_ID_REQUIRED", "X-Project-Id header is required", 422)
        workflow_id = request.path_params["workflow_id"]
        try:
            tenant = _tenant_id(request)
            workflow = await ctx.workflow_store.get_workflow(
                workflow_id,
                tenant_id=tenant,
                project_id=project_id,
            )
            errors = _validate_draft(workflow.draft)
            errors.extend(await _validate_capability_refs(workflow.draft, tenant_id=tenant))
            if errors:
                return _error(request, "INVALID_ARGUMENT", "draft is invalid", 400, details=errors)
            version = await ctx.workflow_store.publish(
                workflow_id,
                tenant_id=tenant,
                project_id=project_id,
            )
        except WorkflowNotFoundError:
            return _error(request, "NOT_FOUND", "workflow not found", 404)
        except WorkflowConflictError as exc:
            return _error(request, "INVALID_ARGUMENT", str(exc), 400)
        return _json(request, workflow_version_to_dict(version))

    async def rollback_workflow(request: Request) -> JSONResponse:
        project_id = _project_id(request)
        if not project_id:
            return _error(request, "ERR_PROJECT_ID_REQUIRED", "X-Project-Id header is required", 422)
        workflow_id = request.path_params["workflow_id"]
        try:
            workflow = await ctx.workflow_store.rollback(
                workflow_id,
                tenant_id=_tenant_id(request),
                project_id=project_id,
            )
        except WorkflowNotFoundError:
            return _error(request, "NOT_FOUND", "workflow not found", 404)
        except WorkflowConflictError as exc:
            return _error(request, "INVALID_ARGUMENT", str(exc), 400)
        return _json(request, workflow_to_dict(workflow))

    async def list_workflow_versions(request: Request) -> JSONResponse:
        project_id = _project_id(request)
        if not project_id:
            return _error(request, "ERR_PROJECT_ID_REQUIRED", "X-Project-Id header is required", 422)
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
                project_id=project_id,
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
            state_exclude_paths_raw = payload.get(STATE_EXCLUDE_PATHS_KEY)
            output_include_paths_raw = payload.get(OUTPUT_INCLUDE_PATHS_KEY)
            version_id = payload.get("version_id") or payload.get("workflow_version_id")
            metadata = payload.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                return _error(request, "INVALID_ARGUMENT", "metadata must be an object", 400)
            try:
                state_exclude_paths = normalize_projection_paths(
                    state_exclude_paths_raw,
                    field_name=STATE_EXCLUDE_PATHS_KEY,
                )
            except ValueError as exc:
                return _error(request, _projection_error_code(exc), str(exc), 400)
            try:
                output_include_paths = normalize_projection_paths(
                    output_include_paths_raw,
                    field_name=OUTPUT_INCLUDE_PATHS_KEY,
                )
            except ValueError as exc:
                return _error(request, _projection_error_code(exc), str(exc), 400)
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
                if mode == "live":
                    run_metadata.setdefault("agent_executor_mode", "live")
                    run_metadata.setdefault("agent_mock", False)
                    run_metadata.setdefault("llm_enabled", True)
                elif mode == "test":
                    run_metadata.setdefault("agent_executor_mode", "mock")
                    run_metadata.setdefault("agent_mock", True)
                    run_metadata.setdefault("llm_enabled", False)
                project_id = str(run_metadata.get("project_id") or "").strip()
                if not project_id:
                    return _error(request, "ERR_PROJECT_ID_REQUIRED", "project_id is required", 422)
                run_metadata["project_id"] = project_id
                tenant = str(run_metadata.get("tenant_id") or _tenant_id(request))
                workflow = await ctx.workflow_store.get_workflow(
                    workflow_id,
                    tenant_id=tenant,
                    project_id=project_id,
                )
                resolved_version_id = version_id or workflow.active_version_id
                if not resolved_version_id:
                    raise WorkflowConflictError("workflow has no active published version")
                version = await ctx.workflow_store.get_version(resolved_version_id, tenant_id=tenant)
                if version.workflow_id != workflow_id:
                    raise WorkflowNotFoundError("workflow version not found")
                default_state_paths, default_output_paths = _version_projection_defaults(version.content)
                resolved_state_paths = (
                    state_exclude_paths if state_exclude_paths_raw is not None else default_state_paths
                )
                resolved_output_paths = (
                    output_include_paths if output_include_paths_raw is not None else default_output_paths
                )
                if resolved_state_paths:
                    run_metadata[STATE_EXCLUDE_PATHS_KEY] = resolved_state_paths
                if resolved_output_paths:
                    run_metadata[OUTPUT_INCLUDE_PATHS_KEY] = resolved_output_paths
                run_metadata["resolved_version"] = version.version_id
                runtime = await _require_runtime()
                run = await runtime.start_run(
                    workflow_id,
                    version.version_id,
                    inputs,
                    mode=mode,
                    metadata=run_metadata,
                )
            except WorkflowNotFoundError:
                return _error(request, "NOT_FOUND", "workflow not found", 404)
            except WorkflowConflictError as exc:
                return _error(request, "INVALID_ARGUMENT", str(exc), 400)
            except ValueError as exc:
                message = str(exc)
                code = (
                    "ERR_CAPABILITY_NOT_FOUND"
                    if "capability" in message.lower() and "not found" in message.lower()
                    else "INVALID_ARGUMENT"
                )
                return _error(request, code, message, 400)
            except RunLedgerWriteRaceError as exc:
                return _error(
                    request,
                    "ERR_WORKFLOW_ENGINE_UNAVAILABLE",
                    str(exc),
                    503,
                    details=_workflow_engine_error_details(exc),
                )
            await _run_store_save(run, tenant_id=tenant)
            return _json(request, run_to_dict(run), status_code=201)

        return await _idempotent(request, f"run_start:{workflow_id}", _start_impl)

    async def create_handoff_package(request: Request) -> Response:
        async def _create_impl() -> Response:
            payload = await request.json()
            if not isinstance(payload, dict):
                return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)
            workflow_id = payload.get("workflow_id")
            if not isinstance(workflow_id, str) or not workflow_id.strip():
                return _error(request, "INVALID_ARGUMENT", "workflow_id is required", 400)
            version_id = payload.get("version_id")
            if version_id is not None and (not isinstance(version_id, str) or not version_id.strip()):
                return _error(request, "INVALID_ARGUMENT", "version_id must be a non-empty string or null", 400)

            package = payload.get("package")
            if not isinstance(package, dict):
                return _error(request, "INVALID_ARGUMENT", "package must be an object", 400)
            context_payload = package.get("context")
            constraints = package.get("constraints")
            expected_result = package.get("expected_result")
            acceptance_checks_raw = package.get("acceptance_checks")
            if not isinstance(context_payload, dict):
                return _error(request, "INVALID_ARGUMENT", "package.context must be an object", 400)
            if not isinstance(constraints, dict):
                return _error(request, "INVALID_ARGUMENT", "package.constraints must be an object", 400)
            if not isinstance(expected_result, dict):
                return _error(request, "INVALID_ARGUMENT", "package.expected_result must be an object", 400)
            if not isinstance(acceptance_checks_raw, list):
                return _error(request, "INVALID_ARGUMENT", "package.acceptance_checks must be an array", 400)
            acceptance_checks: list[dict[str, Any]] = []
            for idx, item in enumerate(acceptance_checks_raw):
                if not isinstance(item, dict):
                    return _error(
                        request,
                        "INVALID_ARGUMENT",
                        f"package.acceptance_checks[{idx}] must be an object",
                        400,
                    )
                acceptance_checks.append(item)

            replay_mode = payload.get("replay_mode", "none")
            if replay_mode not in {"none", "deterministic"}:
                return _error(request, "INVALID_ARGUMENT", "replay_mode must be one of: none, deterministic", 400)

            metadata_raw = payload.get("metadata")
            if metadata_raw is not None and not isinstance(metadata_raw, dict):
                return _error(request, "INVALID_ARGUMENT", "metadata must be an object", 400)
            run_metadata = _run_metadata(request, metadata_raw if isinstance(metadata_raw, dict) else None)
            project_id = str(run_metadata.get("project_id") or "").strip()
            if not project_id:
                return _error(request, "ERR_PROJECT_ID_REQUIRED", "project_id is required", 422)
            run_metadata["project_id"] = project_id

            tenant = str(run_metadata.get("tenant_id") or _tenant_id(request))
            await ctx.ensure_handoff_store()
            if ctx.handoff_store is None:
                return _error(request, "INTERNAL", "handoff store unavailable", 500)
            idempotency_key = request.headers.get("Idempotency-Key")
            handoff_record = await ctx.handoff_store.create(
                workflow_id=workflow_id.strip(),
                version_id=version_id.strip() if isinstance(version_id, str) else None,
                context=context_payload,
                constraints=constraints,
                expected_result=expected_result,
                acceptance_checks=acceptance_checks,
                replay_mode=replay_mode,
                metadata=run_metadata,
                tenant_id=tenant,
                idempotency_key=idempotency_key,
            )

            handoff_metadata = dict(run_metadata)
            handoff_metadata.update(
                {
                    "handoff_id": handoff_record.handoff_id,
                    "handoff_constraints": constraints,
                    "handoff_expected_result": expected_result,
                    "handoff_acceptance_checks": acceptance_checks,
                    "handoff_replay_mode": replay_mode,
                    "deterministic_replay": replay_mode == "deterministic",
                }
            )

            try:
                resolved_workflow_id = workflow_id.strip()
                workflow = await ctx.workflow_store.get_workflow(
                    resolved_workflow_id,
                    tenant_id=tenant,
                    project_id=project_id,
                )
                resolved_version_id = version_id.strip() if isinstance(version_id, str) else workflow.active_version_id
                if not resolved_version_id:
                    raise WorkflowConflictError("workflow has no active published version")
                version = await ctx.workflow_store.get_version(resolved_version_id, tenant_id=tenant)
                if version.workflow_id != resolved_workflow_id:
                    raise WorkflowNotFoundError("workflow version not found")
                default_state_paths, default_output_paths = _version_projection_defaults(version.content)
                if STATE_EXCLUDE_PATHS_KEY not in handoff_metadata and default_state_paths:
                    handoff_metadata[STATE_EXCLUDE_PATHS_KEY] = default_state_paths
                if OUTPUT_INCLUDE_PATHS_KEY not in handoff_metadata and default_output_paths:
                    handoff_metadata[OUTPUT_INCLUDE_PATHS_KEY] = default_output_paths
                handoff_metadata["resolved_version"] = version.version_id
                runtime = await _require_runtime()
                run = await runtime.start_run(
                    resolved_workflow_id,
                    version.version_id,
                    context_payload,
                    mode="async",
                    metadata=handoff_metadata,
                )
            except WorkflowNotFoundError:
                await ctx.handoff_store.update_status(
                    handoff_record.handoff_id,
                    status="FAILED",
                    run_id=None,
                    tenant_id=tenant,
                )
                return _error(request, "NOT_FOUND", "workflow not found", 404)
            except ValueError as exc:
                await ctx.handoff_store.update_status(
                    handoff_record.handoff_id,
                    status="FAILED",
                    run_id=None,
                    tenant_id=tenant,
                )
                message = str(exc)
                code = (
                    "ERR_CAPABILITY_NOT_FOUND"
                    if "capability" in message.lower() and "not found" in message.lower()
                    else "INVALID_ARGUMENT"
                )
                return _error(request, code, message, 400)
            except Exception as exc:
                await ctx.handoff_store.update_status(
                    handoff_record.handoff_id,
                    status="FAILED",
                    run_id=None,
                    tenant_id=tenant,
                )
                return _error(
                    request,
                    "ERR_WORKFLOW_ENGINE_UNAVAILABLE",
                    str(exc),
                    503,
                    details=_workflow_engine_error_details(exc),
                )
            await _run_store_save(run, tenant_id=tenant)
            handoff_record = await ctx.handoff_store.update_status(
                handoff_record.handoff_id,
                status="STARTED",
                run_id=run.id,
                tenant_id=tenant,
            )
            if handoff_record is None:
                return _error(request, "INTERNAL", "handoff store unavailable", 500)
            return _json(request, handoff_to_dict(handoff_record), status_code=201)

        return await _idempotent(request, "handoff_create", _create_impl)

    async def replay_handoff_package(request: Request) -> Response:
        handoff_id = str(request.path_params.get("handoff_id") or "").strip()

        async def _replay_impl() -> Response:
            if not handoff_id:
                return _error(request, "INVALID_ARGUMENT", "handoff_id is required", 400)
            await ctx.ensure_handoff_store()
            if ctx.handoff_store is None:
                return _error(request, "INTERNAL", "handoff store unavailable", 500)
            tenant = _tenant_id(request)
            handoff_record = await ctx.handoff_store.get(handoff_id, tenant_id=tenant)
            if handoff_record is None:
                return _error(request, "ERR_HANDOFF_NOT_FOUND", "handoff package not found", 404)
            if handoff_record.replay_mode != "deterministic":
                return _error(
                    request,
                    "ERR_HANDOFF_REPLAY_NOT_ALLOWED",
                    "handoff package is not deterministic replay enabled",
                    409,
                )

            replay_metadata = dict(handoff_record.metadata or {})
            replay_metadata.update(
                {
                    "handoff_id": handoff_record.handoff_id,
                    "replay_of_handoff_id": handoff_record.handoff_id,
                    "handoff_constraints": handoff_record.constraints,
                    "handoff_expected_result": handoff_record.expected_result,
                    "handoff_acceptance_checks": handoff_record.acceptance_checks,
                    "handoff_replay_mode": handoff_record.replay_mode,
                    "deterministic_replay": True,
                }
            )
            project_id = str(replay_metadata.get("project_id") or "").strip()
            if not project_id:
                return _error(request, "ERR_PROJECT_ID_REQUIRED", "project_id is required", 422)
            try:
                workflow = await ctx.workflow_store.get_workflow(
                    handoff_record.workflow_id,
                    tenant_id=tenant,
                    project_id=project_id,
                )
                resolved_version_id = handoff_record.version_id or workflow.active_version_id
                if not resolved_version_id:
                    raise WorkflowConflictError("workflow has no active published version")
                version = await ctx.workflow_store.get_version(resolved_version_id, tenant_id=tenant)
                if version.workflow_id != handoff_record.workflow_id:
                    raise WorkflowNotFoundError("workflow version not found")
                default_state_paths, default_output_paths = _version_projection_defaults(version.content)
                if STATE_EXCLUDE_PATHS_KEY not in replay_metadata and default_state_paths:
                    replay_metadata[STATE_EXCLUDE_PATHS_KEY] = default_state_paths
                if OUTPUT_INCLUDE_PATHS_KEY not in replay_metadata and default_output_paths:
                    replay_metadata[OUTPUT_INCLUDE_PATHS_KEY] = default_output_paths
                replay_metadata["resolved_version"] = version.version_id
                runtime = await _require_runtime()
                run = await runtime.start_run(
                    handoff_record.workflow_id,
                    version.version_id,
                    handoff_record.context,
                    mode="async",
                    metadata=replay_metadata,
                )
            except WorkflowNotFoundError:
                return _error(request, "NOT_FOUND", "workflow not found", 404)
            except ValueError as exc:
                message = str(exc)
                code = (
                    "ERR_CAPABILITY_NOT_FOUND"
                    if "capability" in message.lower() and "not found" in message.lower()
                    else "INVALID_ARGUMENT"
                )
                return _error(request, code, message, 400)
            except Exception as exc:
                return _error(
                    request,
                    "ERR_WORKFLOW_ENGINE_UNAVAILABLE",
                    str(exc),
                    503,
                    details=_workflow_engine_error_details(exc),
                )

            await _run_store_save(run, tenant_id=tenant)
            handoff_record = await ctx.handoff_store.update_status(
                handoff_record.handoff_id,
                status="REPLAYED",
                run_id=run.id,
                tenant_id=tenant,
            )
            if handoff_record is None:
                return _error(request, "INTERNAL", "handoff store unavailable", 500)
            return _json(request, handoff_to_dict(handoff_record), status_code=200)

        return await _idempotent(request, f"handoff_replay:{handoff_id}", _replay_impl)

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

    async def read_artifact(request: Request) -> JSONResponse:
        artifact_ref_raw = request.path_params.get("artifact_ref")
        artifact_ref = artifact_ref_raw.strip() if isinstance(artifact_ref_raw, str) else ""
        if not artifact_ref:
            return _error(request, "INVALID_ARGUMENT", "artifact_ref is required", 400)
        await ctx.ensure_artifact_store()
        if ctx.artifact_store is None:
            return _error(request, "INTERNAL", "artifact store unavailable", 500)
        tenant_id = _tenant_id(request)
        try:
            artifact = await ctx.artifact_store.read(artifact_ref, tenant_id=tenant_id)
        except ArtifactNotFoundError:
            return _error(request, "artifact.not_found", "artifact not found", 404)
        except ArtifactAccessDeniedError:
            return _error(request, "artifact.access_denied", "artifact access denied", 403)
        except ArtifactExpiredError:
            return _error(request, "artifact.expired", "artifact reference expired", 410)
        return _json(
            request,
            {
                "artifact_ref": artifact.artifact_ref,
                "mime_type": artifact.mime_type,
                "metadata": artifact.metadata,
                "content": artifact.content,
                "created_at": artifact.created_at.isoformat(),
                "expires_at": artifact.expires_at.isoformat() if artifact.expires_at else None,
            },
        )

    async def list_run_ledger(request: Request) -> JSONResponse:
        run_id = request.path_params["run_id"]
        limit_raw = request.query_params.get("limit", "200")
        try:
            limit = int(limit_raw)
        except ValueError:
            return _error(request, "INVALID_ARGUMENT", "limit must be an integer", 400)
        if limit < 1 or limit > 1000:
            return _error(request, "INVALID_ARGUMENT", "limit must be between 1 and 1000", 400)
        await ctx.ensure_run_ledger_store()
        if ctx.run_ledger_store is None:
            return _error(request, "INTERNAL", "run ledger store unavailable", 500)
        entries = await ctx.run_ledger_store.list_run(run_id, tenant_id=_tenant_id(request), limit=limit)
        return _json(
            request,
            {"items": [run_ledger_entry_to_dict(entry) for entry in entries], "next_cursor": None},
        )

    def _parse_context_scope_payload(payload: Any) -> tuple[str, str, Optional[str]]:
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        scope_raw = payload.get("scope")
        scope = scope_raw.strip().lower() if isinstance(scope_raw, str) else ""
        if scope not in {"session", "thread"}:
            raise ValueError("scope must be one of: session, thread")
        scope_id_raw = payload.get("scope_id")
        scope_id = scope_id_raw.strip() if isinstance(scope_id_raw, str) else ""
        if not scope_id:
            raise ValueError("scope_id is required")
        project_id_raw = payload.get("project_id")
        project_id: Optional[str] = None
        if project_id_raw is not None:
            if not isinstance(project_id_raw, str) or not project_id_raw.strip():
                raise ValueError("project_id must be a non-empty string or null")
            project_id = project_id_raw.strip()
        return scope, scope_id, project_id

    async def orchestrator_message(request: Request) -> Response:
        async def _message_impl() -> Response:
            payload = await request.json()
            try:
                routed_request = RoutingRequest.from_payload(payload)
            except ProjectRouterError as exc:
                return _error(request, exc.code, exc.message, exc.status_code)
            except Exception as exc:
                return _error(request, "INVALID_ARGUMENT", str(exc), 400)

            metadata = _run_metadata(request, routed_request.metadata)
            metadata["project_id"] = routed_request.project_id
            metadata["session_id"] = routed_request.session_id
            metadata["user_id"] = routed_request.user_id
            metadata["message_type"] = routed_request.message_type
            if routed_request.action_type:
                metadata["action_type"] = routed_request.action_type

            tenant = _tenant_id(request)
            try:
                await _require_orchestration()
                if ctx.project_router is None:
                    raise RuntimeError("project router is unavailable")
                route = await ctx.project_router.resolve(routed_request, tenant_id=tenant)
                payload = await ctx.project_orchestrator.handle_message(
                    routed_request,
                    route,
                    tenant_id=tenant,
                    metadata=metadata,
                )
            except ProjectRouterError as exc:
                return _error(request, exc.code, exc.message, exc.status_code)
            except OrchestratorRuntimeError as exc:
                return _error(request, exc.code, exc.message, exc.status_code)
            except WorkflowEngineAdapterError as exc:
                status = 503 if exc.retryable else 500
                return _error(request, exc.code, exc.message, status, details=exc.details)
            except Exception as exc:
                return _error(request, "INTERNAL", str(exc), 500)
            return _json(request, payload)

        return await _idempotent(request, "orchestrator_message", _message_impl)

    async def orchestrator_stack(request: Request) -> JSONResponse:
        project_id = request.query_params.get("project_id")
        if not project_id:
            return _error(request, "ERR_PROJECT_ID_REQUIRED", "project_id is required", 422)
        session_id = request.path_params["session_id"]
        tenant = _tenant_id(request)
        try:
            runtime = await _require_orchestration()
            payload = await runtime.get_stack(project_id, session_id, tenant_id=tenant)
        except OrchestratorRuntimeError as exc:
            return _error(request, exc.code, exc.message, exc.status_code)
        except Exception as exc:
            return _error(request, "INTERNAL", str(exc), 500)
        return _json(request, payload)

    async def orchestrator_eval_replay(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)
        if not isinstance(payload, dict):
            return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)

        project_id_raw = payload.get("project_id")
        if not isinstance(project_id_raw, str) or not project_id_raw.strip():
            return _error(request, "ERR_PROJECT_ID_REQUIRED", "project_id is required", 422)
        project_id = project_id_raw.strip()

        orchestrator_id_raw = payload.get("orchestrator_id")
        if orchestrator_id_raw is not None and (
            not isinstance(orchestrator_id_raw, str) or not orchestrator_id_raw.strip()
        ):
            return _error(
                request,
                "INVALID_ARGUMENT",
                "orchestrator_id must be a non-empty string or null",
                400,
            )
        orchestrator_id = orchestrator_id_raw.strip() if isinstance(orchestrator_id_raw, str) else None

        session_id_raw = payload.get("session_id")
        if session_id_raw is None:
            session_id = "eval_session"
        elif isinstance(session_id_raw, str) and session_id_raw.strip():
            session_id = session_id_raw.strip()
        else:
            return _error(request, "INVALID_ARGUMENT", "session_id must be a non-empty string", 400)

        user_id_raw = payload.get("user_id")
        if user_id_raw is None:
            user_id = "eval_user"
        elif isinstance(user_id_raw, str) and user_id_raw.strip():
            user_id = user_id_raw.strip()
        else:
            return _error(request, "INVALID_ARGUMENT", "user_id must be a non-empty string", 400)

        cases_raw = payload.get("cases")
        if not isinstance(cases_raw, list) or not cases_raw:
            return _error(request, "INVALID_ARGUMENT", "cases must be a non-empty array", 400)
        if len(cases_raw) > 1000:
            return _error(request, "INVALID_ARGUMENT", "cases must contain at most 1000 items", 400)

        cases: list[dict[str, Any]] = []
        for index, raw_case in enumerate(cases_raw):
            if not isinstance(raw_case, dict):
                return _error(request, "INVALID_ARGUMENT", f"cases[{index}] must be an object", 400)

            message_text = raw_case.get("message_text")
            if not isinstance(message_text, str) or not message_text.strip():
                return _error(
                    request,
                    "INVALID_ARGUMENT",
                    f"cases[{index}].message_text must be a non-empty string",
                    400,
                )
            normalized_case: dict[str, Any] = {
                "case_id": raw_case.get("case_id"),
                "message_text": message_text.strip(),
            }

            metadata_raw = raw_case.get("metadata")
            if metadata_raw is not None:
                if not isinstance(metadata_raw, dict):
                    return _error(request, "INVALID_ARGUMENT", f"cases[{index}].metadata must be an object", 400)
                normalized_case["metadata"] = dict(metadata_raw)

            for optional_field in ("active_workflow_id", "expected_action", "expected_workflow_id"):
                if optional_field not in raw_case:
                    continue
                value = raw_case.get(optional_field)
                if value is None:
                    normalized_case[optional_field] = None
                    continue
                if not isinstance(value, str) or not value.strip():
                    return _error(
                        request,
                        "INVALID_ARGUMENT",
                        f"cases[{index}].{optional_field} must be a non-empty string or null",
                        400,
                    )
                normalized_case[optional_field] = value.strip()

            cases.append(normalized_case)

        tenant = _tenant_id(request)
        try:
            runtime = await _require_orchestration()
            result = await runtime.evaluate_routing_replay(
                project_id=project_id,
                orchestrator_id=orchestrator_id,
                session_id=session_id,
                user_id=user_id,
                cases=cases,
                tenant_id=tenant,
            )
        except OrchestratorRuntimeError as exc:
            return _error(request, exc.code, exc.message, exc.status_code)
        except Exception as exc:
            return _error(request, "INTERNAL", str(exc), 500)

        return _json(request, result)

    async def orchestrator_context_get(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
            scope, scope_id, project_id = _parse_context_scope_payload(payload)
            keys_raw = payload.get("keys")
            keys: Optional[list[str]]
            if keys_raw is None:
                keys = None
            else:
                if not isinstance(keys_raw, list):
                    return _error(request, "INVALID_ARGUMENT", "keys must be an array", 422)
                keys = []
                for idx, key_raw in enumerate(keys_raw):
                    if not isinstance(key_raw, str) or not key_raw.strip():
                        return _error(
                            request,
                            "INVALID_ARGUMENT",
                            f"keys[{idx}] must be a non-empty string",
                            422,
                        )
                    keys.append(key_raw.strip())
            await ctx.ensure_orchestration()
            if ctx.orchestration_store is None:
                return _error(request, "INTERNAL", "orchestration store unavailable", 500)
            tenant = _tenant_id(request)
            context_payload = await ctx.orchestration_store.get_context_values(
                scope,
                scope_id,
                tenant_id=tenant,
                project_id=project_id,
                keys=keys,
            )
        except ValueError as exc:
            return _error(request, "INVALID_ARGUMENT", str(exc), 422)
        except Exception as exc:
            return _error(request, "INTERNAL", str(exc), 500)
        return _json(
            request,
            {
                "scope": scope,
                "scope_id": scope_id,
                "project_id": project_id,
                "context": context_payload,
                "removed_keys": [],
            },
        )

    async def orchestrator_context_set(request: Request) -> Response:
        async def _set_impl() -> Response:
            try:
                payload = await request.json()
                scope, scope_id, project_id = _parse_context_scope_payload(payload)
                values_raw = payload.get("values")
                if not isinstance(values_raw, dict):
                    return _error(request, "INVALID_ARGUMENT", "values must be an object", 422)
                values = {
                    str(key): value
                    for key, value in values_raw.items()
                    if isinstance(key, str) and key.strip()
                }
                await ctx.ensure_orchestration()
                if ctx.orchestration_store is None:
                    return _error(request, "INTERNAL", "orchestration store unavailable", 500)
                tenant = _tenant_id(request)
                context_payload = await ctx.orchestration_store.set_context_values(
                    scope,
                    scope_id,
                    values=values,
                    tenant_id=tenant,
                    project_id=project_id,
                )
            except ValueError as exc:
                return _error(request, "INVALID_ARGUMENT", str(exc), 422)
            except Exception as exc:
                return _error(request, "INTERNAL", str(exc), 500)
            return _json(
                request,
                {
                    "scope": scope,
                    "scope_id": scope_id,
                    "project_id": project_id,
                    "context": context_payload,
                    "removed_keys": [],
                },
            )

        return await _idempotent(request, "orchestrator_context_set", _set_impl)

    async def orchestrator_context_unset(request: Request) -> Response:
        async def _unset_impl() -> Response:
            try:
                payload = await request.json()
                scope, scope_id, project_id = _parse_context_scope_payload(payload)
                keys_raw = payload.get("keys")
                if not isinstance(keys_raw, list) or not keys_raw:
                    return _error(request, "INVALID_ARGUMENT", "keys must be a non-empty array", 422)
                keys: list[str] = []
                for idx, key_raw in enumerate(keys_raw):
                    if not isinstance(key_raw, str) or not key_raw.strip():
                        return _error(
                            request,
                            "INVALID_ARGUMENT",
                            f"keys[{idx}] must be a non-empty string",
                            422,
                        )
                    keys.append(key_raw.strip())
                await ctx.ensure_orchestration()
                if ctx.orchestration_store is None:
                    return _error(request, "INTERNAL", "orchestration store unavailable", 500)
                tenant = _tenant_id(request)
                removed = await ctx.orchestration_store.unset_context_keys(
                    scope,
                    scope_id,
                    keys=keys,
                    tenant_id=tenant,
                    project_id=project_id,
                )
                context_payload = await ctx.orchestration_store.get_context_values(
                    scope,
                    scope_id,
                    tenant_id=tenant,
                    project_id=project_id,
                    keys=None,
                )
            except ValueError as exc:
                return _error(request, "INVALID_ARGUMENT", str(exc), 422)
            except Exception as exc:
                return _error(request, "INTERNAL", str(exc), 500)
            return _json(
                request,
                {
                    "scope": scope,
                    "scope_id": scope_id,
                    "project_id": project_id,
                    "context": context_payload,
                    "removed_keys": removed,
                },
            )

        return await _idempotent(request, "orchestrator_context_unset", _unset_impl)

    async def cancel_run(request: Request) -> Response:
        run_id = request.path_params["run_id"]

        async def _cancel_impl() -> Response:
            tenant = _tenant_id(request)
            run = await _run_store_get(run_id, tenant_id=tenant)
            if not run:
                return _error(request, "NOT_FOUND", "run not found", 404)
            run.status = "CANCELLED"
            runtime = await _require_runtime()
            cancel_events = [
                RuntimeEvent(
                    type="run_cancelled",
                    run_id=run.id,
                    workflow_id=run.workflow_id,
                    version_id=run.version_id,
                    metadata=dict(run.metadata or {}),
                )
            ]
            await runtime._publish_with_snapshot(run, cancel_events)
            await runtime._notify_hooks(run, cancel_events)
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

    async def openapi_spec(request: Request) -> PlainTextResponse:
        if not _OPENAPI_SPEC_PATH.exists():
            _integration_log(
                request,
                "integration.openapi.read",
                "OpenAPI spec file is missing",
                level="WARNING",
                status_code=404,
            )
            return PlainTextResponse("openapi spec not found", status_code=404)
        content = _OPENAPI_SPEC_PATH.read_text(encoding="utf-8")
        _integration_log(
            request,
            "integration.openapi.read",
            "OpenAPI spec returned",
            status_code=200,
            context={"bytes": len(content)},
        )
        return PlainTextResponse(content, media_type="application/yaml")

    async def api_reference(request: Request) -> PlainTextResponse:
        if not _API_REFERENCE_PATH.exists():
            _integration_log(
                request,
                "integration.api_reference.read",
                "API reference file is missing",
                level="WARNING",
                status_code=404,
            )
            return PlainTextResponse("api reference not found", status_code=404)
        content = _API_REFERENCE_PATH.read_text(encoding="utf-8")
        _integration_log(
            request,
            "integration.api_reference.read",
            "API reference returned",
            status_code=200,
            context={"bytes": len(content)},
        )
        return PlainTextResponse(content, media_type="text/markdown")

    def _public_doc_urls(request: Request) -> Dict[str, str]:
        base_url = str(request.base_url).rstrip("/")
        return {
            "integration_kit_markdown": f"{base_url}/agent-integration-kit",
            "integration_kit_json": f"{base_url}/agent-integration-kit.json",
            "integration_test_ui": f"{base_url}/agent-integration-test",
            "integration_test_json": f"{base_url}/agent-integration-test.json",
            "integration_logs": f"{base_url}/agent-integration-logs",
            "validate_draft": f"{base_url}/agent-integration-test/validate-draft",
            "openapi": f"{base_url}/openapi.yaml",
            "api_reference": f"{base_url}/api-reference",
            "workflow_authoring_guide": f"{base_url}/workflow-authoring-guide",
            "workflow_draft_schema": f"{base_url}/schemas/workflow-draft.schema.json",
            "workflow_export_schema": f"{base_url}/schemas/workflow-export-v1.schema.json",
            "routing_decision_schema": f"{base_url}/schemas/routing-decision.schema.json",
            "projects_list": f"{base_url}/projects",
            "projects_create": f"{base_url}/projects",
            "capabilities_create": f"{base_url}/capabilities",
            "capabilities_versions_template": f"{base_url}/capabilities/{{capability_id}}/versions",
            "project_orchestrator_upsert_template": (
                f"{base_url}/projects/{{project_id}}/orchestrators"
            ),
            "project_workflow_definition_upsert_template": (
                f"{base_url}/projects/{{project_id}}/workflow-definitions"
            ),
            "orchestrator_message": f"{base_url}/orchestrator/messages",
            "orchestrator_eval_replay": f"{base_url}/orchestrator/eval/replay",
            "orchestrator_stack_template": f"{base_url}/orchestrator/sessions/{{session_id}}/stack?project_id={{project_id}}",
            "orchestrator_context_get": f"{base_url}/orchestrator/context/get",
            "orchestrator_context_set": f"{base_url}/orchestrator/context/set",
            "orchestrator_context_unset": f"{base_url}/orchestrator/context/unset",
            "handoff_create": f"{base_url}/handoff/packages",
            "handoff_replay_template": f"{base_url}/handoff/packages/{{handoff_id}}/replay",
            "run_ledger_template": f"{base_url}/runs/{{run_id}}/ledger",
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

        routing_schema = None
        if _ROUTING_DECISION_SCHEMA_PATH.exists():
            try:
                routing_schema = json.loads(_ROUTING_DECISION_SCHEMA_PATH.read_text(encoding="utf-8"))
                add_check("routing_schema_valid_json", "Routing decision schema is valid JSON", True, "ok")
            except Exception as exc:
                add_check(
                    "routing_schema_valid_json",
                    "Routing decision schema is valid JSON",
                    False,
                    str(exc),
                )
        else:
            add_check(
                "routing_schema_valid_json",
                "Routing decision schema is valid JSON",
                False,
                "missing docs/api/schemas/routing-decision.schema.json",
            )

        required_openapi_paths = (
            "/agent-integration-kit",
            "/agent-integration-kit.json",
            "/agent-integration-test",
            "/agent-integration-test.json",
            "/agent-integration-test/validate-draft",
            "/agent-integration-logs",
            "/workflow-authoring-guide",
            "/schemas/workflow-draft.schema.json",
            "/schemas/workflow-export-v1.schema.json",
            "/schemas/routing-decision.schema.json",
            "/projects",
            "/projects/{project_id}/orchestrators",
            "/projects/{project_id}/workflow-definitions",
            "/capabilities",
            "/capabilities/{capability_id}/versions",
            "/orchestrator/messages",
            "/orchestrator/eval/replay",
            "/orchestrator/sessions/{session_id}/stack",
            "/orchestrator/context/get",
            "/orchestrator/context/set",
            "/orchestrator/context/unset",
            "/handoff/packages",
            "/handoff/packages/{handoff_id}/replay",
            "/runs/{run_id}/ledger",
        )
        missing_paths = [path for path in required_openapi_paths if path not in openapi_text]
        add_check(
            "openapi_has_integration_paths",
            "OpenAPI includes integration kit/test/log and reliability endpoints",
            len(missing_paths) == 0,
            "ok" if not missing_paths else f"missing: {', '.join(missing_paths)}",
        )
        add_check(
            "integration_log_buffer_configured",
            "Integration log buffer is configured for troubleshooting",
            integration_logs.maxlen is not None and integration_logs.maxlen >= _MAX_AGENT_INTEGRATION_LOG_LIMIT,
            f"capacity={integration_logs.maxlen}",
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
            set_state_config = (
                draft_schema.get("$defs", {})
                .get("setStateConfig", {})
            )
            set_state_properties = set_state_config.get("properties", {}) if isinstance(set_state_config, dict) else {}
            supports_batch_assignments = isinstance(set_state_properties, dict) and "assignments" in set_state_properties
            add_check(
                "draft_schema_set_state_batch_assignments",
                "Draft schema declares Set State batch assignments support",
                supports_batch_assignments,
                "ok" if supports_batch_assignments else "missing $defs.setStateConfig.properties.assignments",
            )

        if isinstance(routing_schema, dict):
            route_types = (
                routing_schema.get("properties", {})
                .get("route_type", {})
                .get("enum", [])
            )
            add_check(
                "routing_schema_route_types",
                "Routing schema declares required route_type variants",
                isinstance(route_types, list) and "START_WORKFLOW" in route_types and "DISAMBIGUATE" in route_types,
                f"route_types_count={len(route_types) if isinstance(route_types, list) else 0}",
            )

        passed = len([check for check in checks if check["ok"]])
        total = len(checks)

        return {
            "title": "WorkCore Agent Integration Test",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "correlation_id": _correlation_id(request),
            "urls": _public_doc_urls(request),
            "summary": {
                "status": "PASS" if passed == total else "FAIL",
                "passed": passed,
                "failed": total - passed,
                "total": total,
            },
            "checks": checks,
        }

    async def workflow_authoring_guide(request: Request) -> PlainTextResponse:
        if not _WORKFLOW_AUTHORING_GUIDE_PATH.exists():
            _integration_log(
                request,
                "integration.workflow_authoring_guide.read",
                "Workflow authoring guide is missing",
                level="WARNING",
                status_code=404,
            )
            return PlainTextResponse("workflow authoring guide not found", status_code=404)
        content = _WORKFLOW_AUTHORING_GUIDE_PATH.read_text(encoding="utf-8")
        _integration_log(
            request,
            "integration.workflow_authoring_guide.read",
            "Workflow authoring guide returned",
            status_code=200,
            context={"bytes": len(content)},
        )
        return PlainTextResponse(content, media_type="text/markdown")

    async def workflow_draft_schema(request: Request) -> Response:
        if not _WORKFLOW_DRAFT_SCHEMA_PATH.exists():
            _integration_log(
                request,
                "integration.workflow_draft_schema.read",
                "Workflow draft schema is missing",
                level="WARNING",
                status_code=404,
            )
            return PlainTextResponse("workflow draft schema not found", status_code=404)
        try:
            payload = json.loads(_WORKFLOW_DRAFT_SCHEMA_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            _integration_log(
                request,
                "integration.workflow_draft_schema.read",
                "Workflow draft schema JSON is invalid",
                level="ERROR",
                status_code=500,
                context={"error": str(exc)},
            )
            return PlainTextResponse("workflow draft schema is invalid", status_code=500)
        _integration_log(
            request,
            "integration.workflow_draft_schema.read",
            "Workflow draft schema returned",
            status_code=200,
            context={"top_level_keys": len(payload) if isinstance(payload, dict) else 0},
        )
        return JSONResponse(payload)

    async def workflow_export_schema(request: Request) -> Response:
        if not _WORKFLOW_EXPORT_SCHEMA_PATH.exists():
            _integration_log(
                request,
                "integration.workflow_export_schema.read",
                "Workflow export schema is missing",
                level="WARNING",
                status_code=404,
            )
            return PlainTextResponse("workflow export schema not found", status_code=404)
        try:
            payload = json.loads(_WORKFLOW_EXPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            _integration_log(
                request,
                "integration.workflow_export_schema.read",
                "Workflow export schema JSON is invalid",
                level="ERROR",
                status_code=500,
                context={"error": str(exc)},
            )
            return PlainTextResponse("workflow export schema is invalid", status_code=500)
        _integration_log(
            request,
            "integration.workflow_export_schema.read",
            "Workflow export schema returned",
            status_code=200,
            context={"top_level_keys": len(payload) if isinstance(payload, dict) else 0},
        )
        return JSONResponse(payload)

    async def routing_decision_schema(request: Request) -> Response:
        if not _ROUTING_DECISION_SCHEMA_PATH.exists():
            _integration_log(
                request,
                "integration.routing_decision_schema.read",
                "Routing decision schema is missing",
                level="WARNING",
                status_code=404,
            )
            return PlainTextResponse("routing decision schema not found", status_code=404)
        try:
            payload = json.loads(_ROUTING_DECISION_SCHEMA_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            _integration_log(
                request,
                "integration.routing_decision_schema.read",
                "Routing decision schema JSON is invalid",
                level="ERROR",
                status_code=500,
                context={"error": str(exc)},
            )
            return PlainTextResponse("routing decision schema is invalid", status_code=500)
        _integration_log(
            request,
            "integration.routing_decision_schema.read",
            "Routing decision schema returned",
            status_code=200,
            context={"top_level_keys": len(payload) if isinstance(payload, dict) else 0},
        )
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
            f"- Routing decision schema: {urls['routing_decision_schema']}",
            f"- Project list endpoint: {urls['projects_list']}",
            f"- Project create endpoint: {urls['projects_create']}",
            f"- Capability registry create endpoint: {urls['capabilities_create']}",
            f"- Capability versions endpoint template: {urls['capabilities_versions_template']}",
            f"- Project orchestrator upsert endpoint template: {urls['project_orchestrator_upsert_template']}",
            f"- Project workflow-definition upsert endpoint template: {urls['project_workflow_definition_upsert_template']}",
            f"- Orchestrator message endpoint: {urls['orchestrator_message']}",
            f"- Orchestrator eval replay endpoint: {urls['orchestrator_eval_replay']}",
            f"- Orchestrator stack endpoint template: {urls['orchestrator_stack_template']}",
            f"- Orchestrator context.get endpoint: {urls['orchestrator_context_get']}",
            f"- Orchestrator context.set endpoint: {urls['orchestrator_context_set']}",
            f"- Orchestrator context.unset endpoint: {urls['orchestrator_context_unset']}",
            f"- Atomic handoff endpoint: {urls['handoff_create']}",
            f"- Handoff replay endpoint template: {urls['handoff_replay_template']}",
            f"- Run ledger endpoint template: {urls['run_ledger_template']}",
            f"- Integration test UI: {urls['integration_test_ui']}",
            f"- Integration test JSON: {urls['integration_test_json']}",
            f"- Integration logs JSON: {urls['integration_logs']}",
            f"- Draft validator endpoint: {urls['validate_draft']}",
            "",
            "## Machine-readable bundle",
            f"- JSON bundle: {urls['integration_kit_json']}",
            "",
            "## Detailed troubleshooting logs",
            "- Use integration logs to debug onboarding failures quickly.",
            f"- Logs endpoint: {urls['integration_logs']}",
            "- Filter logs by `correlation_id`, `trace_id`, or `event`.",
            "",
            "## API changelog policy",
            "- Every public API contract update must include a same-change update to `CHANGELOG.md`.",
            "- Each API changelog entry must explicitly describe the delta vs previous API version and include:",
            "  - `Previous API version`",
            "  - `Current API version`",
            "  - concrete Added/Changed/Deprecated/Removed items",
            "",
            "## Minimum integration steps",
            "1. Read OpenAPI and API reference.",
            "2. List available projects via `GET /projects` or create scope via `POST /projects` (`project_id` + `project_name`).",
            "3. Define workflow goal and output, then follow workflow authoring guide.",
            "4. Validate workflow payloads with the provided schemas (including `set_state.assignments[]` support for batch mappings).",
            "5. Register capability contracts via `POST /capabilities` before publishing capability-pinned steps.",
            "6. Create/publish workflow via `/workflows` and `/workflows/{workflow_id}/publish`.",
            "7. Register workflow in project routing index via `POST /projects/{project_id}/workflow-definitions`.",
            "8. Configure project orchestrator via `POST /projects/{project_id}/orchestrators`.",
            "9. Run integration checks and ensure status=PASS.",
            "10. For project routing, call `POST /orchestrator/messages` with `project_id`, `session_id`, `user_id`, and `message`.",
            "11. For offline routing quality checks, call `POST /orchestrator/eval/replay` with labeled cases.",
            "12. Use context API (`/orchestrator/context/get|set|unset`) for thread/session context hydration.",
            "13. For direct workflow mode, set `workflow_id` in the same orchestrator request.",
            "14. For deterministic package transfer, use `POST /handoff/packages` and replay via `/handoff/packages/{handoff_id}/replay`.",
            "15. For diagnostics, call `GET /orchestrator/sessions/{session_id}/stack?project_id=...` and `GET /runs/{run_id}/ledger`.",
            "16. If checks fail, inspect `/agent-integration-logs` and fix by correlation/trace context.",
            "",
            "## Special instructions and examples",
            "- Keep tenant scope consistent: use the same `X-Tenant-Id` for `/projects`, project-registry bootstrap, and `/orchestrator/messages`.",
            "- Prefer one `set_state` node with `assignments[]` instead of long chains of one-field assignments.",
            "- For direct orchestrator mode (`workflow_id` in message), register the workflow first via `POST /projects/{project_id}/workflow-definitions`.",
            "- For orchestrated mode (no `workflow_id`), configure default orchestrator via `POST /projects/{project_id}/orchestrators` with `set_as_default=true`.",
            "- If your edge requires Cloudflare Access, include CF-Access headers on every protected API request.",
            "",
            "### Example: project bootstrap + registry binding",
            "```bash",
            "BASE_URL=\"https://api.runwcr.com\"",
            "TOKEN=\"<bearer_token>\"",
            "TENANT=\"local\"",
            "PROJECT_ID=\"project_future_bank_demo_2026_02\"",
            "PROJECT_NAME=\"Future Bank Demo 2026 02\"",
            "WORKFLOW_ID=\"wf_91ca7892\"",
            "",
            "curl -X POST \"$BASE_URL/projects\" \\",
            "  -H \"Authorization: Bearer $TOKEN\" \\",
            "  -H \"X-Tenant-Id: $TENANT\" \\",
            "  -H \"Content-Type: application/json\" \\",
            "  -d '{\"project_id\":\"'\"$PROJECT_ID\"'\",\"project_name\":\"'\"$PROJECT_NAME\"'\",\"settings\":{\"orchestrator_enabled\":true}}'",
            "",
            "curl -X POST \"$BASE_URL/projects/$PROJECT_ID/workflow-definitions\" \\",
            "  -H \"Authorization: Bearer $TOKEN\" \\",
            "  -H \"X-Tenant-Id: $TENANT\" \\",
            "  -H \"Content-Type: application/json\" \\",
            "  -d '{\"workflow_id\":\"'\"$WORKFLOW_ID\"'\",\"name\":\"Future bank demo\",\"description\":\"Routing index record\",\"tags\":[\"bank\",\"demo\"],\"examples\":[\"open account\"],\"active\":true,\"is_fallback\":false}'",
            "",
            "curl -X POST \"$BASE_URL/projects/$PROJECT_ID/orchestrators\" \\",
            "  -H \"Authorization: Bearer $TOKEN\" \\",
            "  -H \"X-Tenant-Id: $TENANT\" \\",
            "  -H \"Content-Type: application/json\" \\",
            "  -d '{\"orchestrator_id\":\"orc_default\",\"name\":\"Default orchestrator\",\"routing_policy\":{\"confidence_threshold\":0.6,\"switch_margin\":0.2,\"max_disambiguation_turns\":2,\"top_k_candidates\":10},\"fallback_workflow_id\":\"'\"$WORKFLOW_ID\"'\",\"prompt_profile\":\"default\",\"set_as_default\":true}'",
            "```",
            "",
            "### Example: orchestrator message",
            "```bash",
            "curl -X POST \"$BASE_URL/orchestrator/messages\" \\",
            "  -H \"Authorization: Bearer $TOKEN\" \\",
            "  -H \"X-Tenant-Id: $TENANT\" \\",
            "  -H \"Content-Type: application/json\" \\",
            "  -d '{\"project_id\":\"'\"$PROJECT_ID\"'\",\"session_id\":\"sess_001\",\"user_id\":\"user_001\",\"workflow_id\":\"'\"$WORKFLOW_ID\"'\",\"message\":{\"id\":\"msg_001\",\"text\":\"start\"}}'",
            "```",
        ]
        _integration_log(
            request,
            "integration.kit.read",
            "Agent integration kit returned",
            status_code=200,
            context={"urls_count": len(urls)},
        )
        return PlainTextResponse("\n".join(lines), media_type="text/markdown")

    async def agent_integration_kit_json(request: Request) -> JSONResponse:
        if not _WORKFLOW_AUTHORING_GUIDE_PATH.exists():
            _integration_log(
                request,
                "integration.kit_json.read",
                "Workflow authoring guide is missing for kit JSON",
                level="WARNING",
                status_code=404,
            )
            return _error(request, "NOT_FOUND", "workflow authoring guide not found", 404)
        if not _API_REFERENCE_PATH.exists():
            _integration_log(
                request,
                "integration.kit_json.read",
                "API reference is missing for kit JSON",
                level="WARNING",
                status_code=404,
            )
            return _error(request, "NOT_FOUND", "api reference not found", 404)
        if not _WORKFLOW_DRAFT_SCHEMA_PATH.exists():
            _integration_log(
                request,
                "integration.kit_json.read",
                "Workflow draft schema is missing for kit JSON",
                level="WARNING",
                status_code=404,
            )
            return _error(request, "NOT_FOUND", "workflow draft schema not found", 404)
        if not _WORKFLOW_EXPORT_SCHEMA_PATH.exists():
            _integration_log(
                request,
                "integration.kit_json.read",
                "Workflow export schema is missing for kit JSON",
                level="WARNING",
                status_code=404,
            )
            return _error(request, "NOT_FOUND", "workflow export schema not found", 404)
        if not _ROUTING_DECISION_SCHEMA_PATH.exists():
            _integration_log(
                request,
                "integration.kit_json.read",
                "Routing decision schema is missing for kit JSON",
                level="WARNING",
                status_code=404,
            )
            return _error(request, "NOT_FOUND", "routing decision schema not found", 404)

        try:
            draft_schema = json.loads(_WORKFLOW_DRAFT_SCHEMA_PATH.read_text(encoding="utf-8"))
            export_schema = json.loads(_WORKFLOW_EXPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
            routing_schema = json.loads(_ROUTING_DECISION_SCHEMA_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            _integration_log(
                request,
                "integration.kit_json.read",
                "Failed to parse local schema files for kit JSON",
                level="ERROR",
                status_code=500,
                context={"error": str(exc)},
            )
            return _error(request, "INTERNAL", "invalid local schema files", 500)

        integration_test = _integration_check_report(request)
        summary = integration_test.get("summary", {})
        payload = {
            "title": "WorkCore Agent Integration Kit",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "urls": _public_doc_urls(request),
            "integration_test": integration_test,
            "docs": {
                "api_reference_markdown": _API_REFERENCE_PATH.read_text(encoding="utf-8"),
                "workflow_authoring_guide_markdown": _WORKFLOW_AUTHORING_GUIDE_PATH.read_text(encoding="utf-8"),
            },
            "schemas": {
                "workflow_draft": draft_schema,
                "workflow_export_v1": export_schema,
                "routing_decision": routing_schema,
            },
        }
        _integration_log(
            request,
            "integration.kit_json.read",
            "Agent integration kit JSON returned",
            status_code=200,
            context={
                "integration_status": summary.get("status"),
                "checks_total": summary.get("total"),
                "checks_failed": summary.get("failed"),
            },
        )
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
    <a href="/agent-integration-logs?limit=100" target="_blank" rel="noopener noreferrer">Open integration logs</a>
  </div>
  <div id="summary" class="card muted">Loading...</div>
  <div id="checks" class="card"></div>

  <h2>Integration Logs</h2>
  <p class="muted">Use logs to troubleshoot integration errors by correlation or trace context.</p>
  <div class="row">
    <button id="refreshLogs">Refresh logs</button>
  </div>
  <pre id="logsOutput">No logs loaded yet.</pre>

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
    const logsOutput = document.getElementById('logsOutput');
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
      await runLogs();
    }

    async function runLogs() {
      const response = await fetch('/agent-integration-logs?limit=50');
      const payload = await response.json();
      logsOutput.textContent = JSON.stringify(payload, null, 2);
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
    document.getElementById('refreshLogs').addEventListener('click', runLogs);
    document.getElementById('validate').addEventListener('click', validateDraft);
    runChecks();
  </script>
</body>
</html>"""
        _integration_log(
            request,
            "integration.test_ui.read",
            "Agent integration test UI returned",
            status_code=200,
        )
        return PlainTextResponse(html, media_type="text/html")

    async def agent_integration_test_json(request: Request) -> JSONResponse:
        report = _integration_check_report(request)
        summary = report.get("summary", {})
        _integration_log(
            request,
            "integration.test_json.read",
            "Agent integration test report returned",
            status_code=200,
            context={
                "integration_status": summary.get("status"),
                "checks_total": summary.get("total"),
                "checks_failed": summary.get("failed"),
            },
        )
        return _json(request, report)

    async def agent_validate_draft(request: Request) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            _integration_log(
                request,
                "integration.draft.validate",
                "Draft validation request body is not an object",
                level="WARNING",
                status_code=400,
            )
            return _error(request, "INVALID_ARGUMENT", "request body must be an object", 400)
        draft = payload.get("draft", payload)
        if not isinstance(draft, dict):
            _integration_log(
                request,
                "integration.draft.validate",
                "Draft payload is not an object",
                level="WARNING",
                status_code=400,
            )
            return _error(request, "INVALID_ARGUMENT", "draft must be an object", 400)
        errors = _validate_draft(draft)
        node_count = len(draft.get("nodes")) if isinstance(draft.get("nodes"), list) else 0
        edge_count = len(draft.get("edges")) if isinstance(draft.get("edges"), list) else 0
        valid = len(errors) == 0
        _integration_log(
            request,
            "integration.draft.validate",
            "Draft validated against runtime publish rules",
            level="INFO" if valid else "WARNING",
            status_code=200,
            context={
                "valid": valid,
                "errors_count": len(errors),
                "nodes_count": node_count,
                "edges_count": edge_count,
                "first_error": errors[0] if errors else None,
            },
        )
        return _json(
            request,
            {
                "valid": valid,
                "errors": errors,
            },
        )

    async def agent_integration_logs(request: Request) -> JSONResponse:
        limit_raw = request.query_params.get("limit", str(_DEFAULT_AGENT_INTEGRATION_LOG_LIMIT))
        try:
            limit = int(limit_raw)
        except ValueError:
            _integration_log(
                request,
                "integration.logs.read",
                "Invalid limit query parameter for integration logs",
                level="WARNING",
                status_code=400,
                context={"limit_raw": limit_raw},
            )
            return _error(request, "INVALID_ARGUMENT", "limit must be an integer", 400)
        if limit < 1 or limit > _MAX_AGENT_INTEGRATION_LOG_LIMIT:
            _integration_log(
                request,
                "integration.logs.read",
                "Integration logs limit is out of supported range",
                level="WARNING",
                status_code=400,
                context={"limit": limit, "max_limit": _MAX_AGENT_INTEGRATION_LOG_LIMIT},
            )
            return _error(
                request,
                "INVALID_ARGUMENT",
                f"limit must be between 1 and {_MAX_AGENT_INTEGRATION_LOG_LIMIT}",
                400,
            )
        correlation_filter = request.query_params.get("correlation_id")
        trace_filter = request.query_params.get("trace_id")
        event_filter = request.query_params.get("event")

        entries = list(integration_logs)
        filtered: list[Dict[str, Any]] = []
        for entry in reversed(entries):
            if correlation_filter and entry.get("correlation_id") != correlation_filter:
                continue
            if trace_filter and entry.get("trace_id") != trace_filter:
                continue
            if event_filter and entry.get("event") != event_filter:
                continue
            filtered.append(entry)

        returned_entries = filtered[:limit]
        total_filtered = len(filtered)
        payload = {
            "title": "WorkCore Agent Integration Logs",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "filters": {
                "limit": limit,
                "correlation_id": correlation_filter,
                "trace_id": trace_filter,
                "event": event_filter,
            },
            "summary": {
                "total": total_filtered,
                "returned": len(returned_entries),
                "has_more": total_filtered > len(returned_entries),
            },
            "entries": returned_entries,
        }
        _integration_log(
            request,
            "integration.logs.read",
            "Agent integration logs returned",
            status_code=200,
            context={
                "requested_limit": limit,
                "returned": len(returned_entries),
                "total_filtered": total_filtered,
                "has_more": total_filtered > len(returned_entries),
            },
        )
        return _json(request, payload)

    async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        _integration_log(
            request,
            "api.unhandled_exception",
            str(exc),
            level="ERROR",
            status_code=500,
            context={"exception_type": exc.__class__.__name__},
        )
        return _error(request, "INTERNAL", "internal server error", 500)

    routes = [
        Route("/health", health),
        Route("/openapi.yaml", openapi_spec),
        Route("/api-reference", api_reference),
        Route("/workflow-authoring-guide", workflow_authoring_guide),
        Route("/schemas/workflow-draft.schema.json", workflow_draft_schema),
        Route("/schemas/workflow-export-v1.schema.json", workflow_export_schema),
        Route("/schemas/routing-decision.schema.json", routing_decision_schema),
        Route("/agent-integration-kit", agent_integration_kit),
        Route("/agent-integration-kit.json", agent_integration_kit_json),
        Route("/agent-integration-test", agent_integration_test),
        Route("/agent-integration-test.json", agent_integration_test_json),
        Route("/agent-integration-test/validate-draft", agent_validate_draft, methods=["POST"]),
        Route("/agent-integration-logs", agent_integration_logs),
        Route("/projects", list_projects, methods=["GET"]),
        Route("/projects", create_project, methods=["POST"]),
        Route("/projects/{project_id}", update_project, methods=["PATCH"]),
        Route("/projects/{project_id}", delete_project, methods=["DELETE"]),
        Route("/projects/{project_id}/orchestrators", upsert_project_orchestrator, methods=["POST"]),
        Route("/projects/{project_id}/workflow-definitions", upsert_project_workflow_definition, methods=["POST"]),
        Route("/capabilities", create_capability, methods=["POST"]),
        Route("/capabilities", list_capabilities, methods=["GET"]),
        Route("/capabilities/{capability_id}/versions", list_capability_versions, methods=["GET"]),
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
        Route("/orchestrator/messages", orchestrator_message, methods=["POST"]),
        Route("/orchestrator/eval/replay", orchestrator_eval_replay, methods=["POST"]),
        Route("/orchestrator/sessions/{session_id}/stack", orchestrator_stack, methods=["GET"]),
        Route("/orchestrator/context/get", orchestrator_context_get, methods=["POST"]),
        Route("/orchestrator/context/set", orchestrator_context_set, methods=["POST"]),
        Route("/orchestrator/context/unset", orchestrator_context_unset, methods=["POST"]),
        Route("/handoff/packages", create_handoff_package, methods=["POST"]),
        Route("/handoff/packages/{handoff_id}/replay", replay_handoff_package, methods=["POST"]),
        Route("/runs", list_runs, methods=["GET"]),
        Route("/artifacts/{artifact_ref}", read_artifact, methods=["GET"]),
        Route("/runs/{run_id}", get_run, methods=["GET"]),
        Route("/runs/{run_id}/ledger", list_run_ledger, methods=["GET"]),
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

    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        exception_handlers={Exception: _unhandled_exception},
    )
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
        or "http://workcore.build,https://workcore.build,http://workcore.build:8080,https://workcore.build:8443,http://hq21.build,https://hq21.build"
    )
    allow_origins = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app
