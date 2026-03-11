from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
from typing import Any, Optional

import asyncpg
from minio import Minio
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route

from chatkit.server import NonStreamingResult, StreamingResult

from apps.orchestrator.api.store import PostgresRunStore
from apps.orchestrator.api.workflow_store import PostgresWorkflowStore, WorkflowNotFoundError
from apps.orchestrator.chatkit.config import ChatKitConfig
from apps.orchestrator.chatkit.context import ChatKitContext
from apps.orchestrator.chatkit.idempotency import IdempotencyStore
from apps.orchestrator.chatkit.runtime_service import ChatKitRuntimeService
from apps.orchestrator.chatkit.object_store import MinioAttachmentStore
from apps.orchestrator.chatkit.pg_store import PostgresChatKitStore
from apps.orchestrator.chatkit.scope_resolution import (
    CHAT_RESOLUTION_MODE_ERROR,
    ChatThreadResolutionError,
    resolve_thread_create_scope,
)
from apps.orchestrator.chatkit.server import (
    InvalidTranscriptionInputError,
    TranscriptionUnavailableError,
    WorkflowChatKitServer,
)
from apps.orchestrator.executors import (
    AGENTS_AVAILABLE,
    AgentExecutor,
    IntegrationHTTPEgressPolicy,
    IntegrationHTTPExecutor,
    MCPExecutor,
    MockAgentExecutor,
    mcp_client_from_env,
)
from apps.orchestrator.orchestrator_runtime.project_settings import get_default_chat_workflow_id
from apps.orchestrator.orchestrator_runtime.store import PostgresOrchestrationStore
from apps.orchestrator.runtime import Edge, Node, SimpleEvaluator, Workflow, CelEvaluator
from apps.orchestrator.streaming import EventPublisher, InMemoryEventBus, InMemoryEventStore
from apps.orchestrator.runtime.env import get_env

_CHAT_ENDPOINT_PATH = "/chat"
_CHATKIT_ALIAS_PATH = "/chatkit"
_CHATKIT_ALIAS_DEPRECATION = "true"
_CHATKIT_ALIAS_SUNSET_AT = datetime(2026, 4, 4, 0, 0, 0, tzinfo=timezone.utc)
_CHATKIT_ALIAS_SUNSET_HTTP_DATE = "Sat, 04 Apr 2026 00:00:00 GMT"

logger = logging.getLogger(__name__)


def _chatkit_alias_is_sunset(now: datetime | None = None) -> bool:
    current = now or datetime.now(timezone.utc)
    return current >= _CHATKIT_ALIAS_SUNSET_AT


def _attach_chatkit_alias_headers(response: Response) -> Response:
    response.headers["Deprecation"] = _CHATKIT_ALIAS_DEPRECATION
    response.headers["Sunset"] = _CHATKIT_ALIAS_SUNSET_HTTP_DATE
    return response


def _correlation_id(request: Request) -> str:
    existing = getattr(request.state, "correlation_id", None)
    if isinstance(existing, str) and existing:
        return existing
    incoming = (request.headers.get("X-Correlation-Id") or "").strip()
    correlation_id = incoming or f"corr_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')[:18]}"
    request.state.correlation_id = correlation_id
    return correlation_id


def _error_response(
    request: Request,
    code: str,
    message: str,
    status_code: int,
    *,
    details: Any = None,
) -> JSONResponse:
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(
        {"error": error, "correlation_id": _correlation_id(request)},
        status_code=status_code,
    )


def _audio_filename_from_media_type(media_type: str) -> str:
    normalized = media_type.strip().lower()
    if normalized == "audio/ogg":
        return "input.ogg"
    if normalized == "audio/mp4":
        return "input.m4a"
    return "input.webm"


def _build_transcriber(cfg: ChatKitConfig):
    api_key = cfg.stt_api_key
    azure_endpoint = (get_env("AZURE_OPENAI_ENDPOINT") or "").strip()
    azure_api_version = (get_env("AZURE_OPENAI_API_VERSION") or "").strip()

    if azure_endpoint:
        if not api_key or not azure_api_version:
            return None
        from openai import AsyncAzureOpenAI

        client = AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=azure_api_version,
            timeout=cfg.stt_timeout_seconds,
        )
    else:
        if not api_key:
            return None
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key, timeout=cfg.stt_timeout_seconds)

    async def _transcriber(audio_input, _context):
        response = await client.audio.transcriptions.create(
            model=cfg.stt_model,
            file=(
                _audio_filename_from_media_type(audio_input.media_type),
                audio_input.data,
                audio_input.mime_type,
            ),
        )
        text: Optional[str] = None
        if isinstance(response, dict):
            text = response.get("text")
        else:
            text = getattr(response, "text", None)
            if text is None and hasattr(response, "model_dump"):
                dumped = response.model_dump()
                if isinstance(dumped, dict):
                    text = dumped.get("text")
        if not isinstance(text, str):
            raise RuntimeError("transcription response is missing text")
        return text

    return _transcriber


async def load_workflow_from_db(
    pool: asyncpg.Pool,
    workflow_id: str,
    version_id: str | None = None,
    tenant_id: str = "",
) -> Workflow:
    if not tenant_id:
        raise RuntimeError("X-Tenant-Id is required")
    if version_id:
        row = await pool.fetchrow(
            "select id, content from workflow_versions where id = $1 and workflow_id = $2 and tenant_id = $3",
            version_id,
            workflow_id,
            tenant_id,
        )
    else:
        workflow_row = await pool.fetchrow(
            "select active_version_id from workflows where id = $1 and tenant_id = $2",
            workflow_id,
            tenant_id,
        )
        active_version_id = workflow_row["active_version_id"] if workflow_row else None
        if active_version_id:
            row = await pool.fetchrow(
                "select id, content from workflow_versions where id = $1 and tenant_id = $2",
                active_version_id,
                tenant_id,
            )
        else:
            row = await pool.fetchrow(
                """
                select id, content
                from workflow_versions
                where workflow_id = $1 and tenant_id = $2
                order by version_number desc
                limit 1
                """,
                workflow_id,
                tenant_id,
            )

    if not row:
        raise RuntimeError("Workflow version not found for ChatKit service")

    content = row["content"] or {}
    if isinstance(content, str):
        import json
        content = json.loads(content)
    nodes_raw = content.get("nodes") or []
    edges_raw = content.get("edges") or []
    if not nodes_raw:
        raise RuntimeError("Workflow content is missing nodes")

    nodes = {
        node["id"]: Node(
            node["id"],
            node.get("type", ""),
            node.get("config", {}),
        )
        for node in nodes_raw
        if isinstance(node, dict) and node.get("id")
    }
    edges = [
        Edge(edge.get("source", ""), edge.get("target", ""))
        for edge in edges_raw
        if isinstance(edge, dict)
    ]

    return Workflow(
        id=workflow_id,
        version_id=row["id"],
        nodes=nodes,
        edges=edges,
    )


def create_service_app() -> Starlette:
    @asynccontextmanager
    async def lifespan(app: Starlette):
        cfg = ChatKitConfig.from_env()
        pool = await asyncpg.create_pool(cfg.database_url)
        store = PostgresChatKitStore(pool)
        orchestration_store = PostgresOrchestrationStore(pool)
        workflow_store = PostgresWorkflowStore(pool)

        client = Minio(
            cfg.object_endpoint,
            access_key=cfg.object_access_key,
            secret_key=cfg.object_secret_key,
            secure=cfg.object_secure,
        )
        if cfg.create_bucket and not client.bucket_exists(cfg.object_bucket):
            client.make_bucket(cfg.object_bucket)

        attachment_store = MinioAttachmentStore(
            pool=pool,
            client=client,
            bucket=cfg.object_bucket,
            prefix=cfg.object_prefix,
            upload_expires_seconds=cfg.upload_expires_seconds,
        )
        idempotency = IdempotencyStore(pool, ttl_seconds=cfg.idempotency_ttl_seconds)

        event_store = InMemoryEventStore()
        event_bus = InMemoryEventBus()
        publisher = EventPublisher(event_store, event_bus)
        try:
            evaluator = CelEvaluator()
        except Exception:
            evaluator = SimpleEvaluator()

        async def loader(workflow_id: str, version_id: str | None, tenant_id: str) -> Workflow:
            return await load_workflow_from_db(pool, workflow_id, version_id, tenant_id=tenant_id)

        executor_mode = (get_env("AGENT_EXECUTOR_MODE") or "").strip().lower()
        integration_http_policy = IntegrationHTTPEgressPolicy.from_env(get_env)
        mcp_client = mcp_client_from_env(get_env)
        executors: dict[str, Any] = {
            "agent_mock": MockAgentExecutor(),
            "integration_http": IntegrationHTTPExecutor(egress_policy=integration_http_policy),
            "mcp": MCPExecutor(mcp_client),
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

        service = ChatKitRuntimeService(
            publisher=publisher,
            store=event_store,
            bus=event_bus,
            evaluator=evaluator,
            workflow_loader=loader,
            executors=executors,
        )

        app.state.server = WorkflowChatKitServer(
            store,
            attachment_store,
            transcriber=_build_transcriber(cfg),
            stt_allowed_media_types=set(cfg.stt_allowed_media_types),
            stt_max_audio_bytes=cfg.stt_max_audio_bytes,
        )
        app.state.context = ChatKitContext(
            service=service,
            run_store=PostgresRunStore(pool),
            tenant_id="local",
            idempotency=idempotency,
        )
        app.state.pool = pool
        app.state.service = service
        app.state.config = cfg
        app.state.orchestration_store = orchestration_store
        app.state.workflow_store = workflow_store

        try:
            yield
        finally:
            await pool.close()

    async def resolve_project_default_workflow(project_id: str, tenant_id: str) -> tuple[str, str | None]:
        orchestration_store: PostgresOrchestrationStore = app.state.orchestration_store
        workflow_store: PostgresWorkflowStore = app.state.workflow_store

        project = await orchestration_store.get_project(project_id, tenant_id)
        if project is None:
            raise ChatThreadResolutionError("ERR_PROJECT_NOT_FOUND", "project not found", 404, project_id=project_id)

        default_workflow_id = get_default_chat_workflow_id(project.settings)
        if not default_workflow_id:
            raise ChatThreadResolutionError(
                "CHAT_DEFAULT_WORKFLOW_NOT_CONFIGURED",
                "project default chat workflow is not configured",
                409,
                project_id=project_id,
            )

        try:
            workflow = await workflow_store.get_workflow(
                default_workflow_id,
                tenant_id=tenant_id,
                project_id=project_id,
            )
        except WorkflowNotFoundError as exc:
            raise ChatThreadResolutionError(
                "CHAT_DEFAULT_WORKFLOW_NOT_FOUND",
                "project default chat workflow is missing or not published",
                404,
                project_id=project_id,
                workflow_id=default_workflow_id,
            ) from exc

        active_version_id = workflow.active_version_id
        if not active_version_id:
            raise ChatThreadResolutionError(
                "CHAT_DEFAULT_WORKFLOW_NOT_FOUND",
                "project default chat workflow is missing or not published",
                404,
                project_id=project_id,
                workflow_id=default_workflow_id,
            )

        try:
            await workflow_store.get_version(active_version_id, tenant_id=tenant_id)
        except WorkflowNotFoundError as exc:
            raise ChatThreadResolutionError(
                "CHAT_DEFAULT_WORKFLOW_NOT_FOUND",
                "project default chat workflow is missing or not published",
                404,
                project_id=project_id,
                workflow_id=default_workflow_id,
            ) from exc
        return default_workflow_id, active_version_id

    async def chatkit(request: Request):
        is_chatkit_alias = request.url.path == _CHATKIT_ALIAS_PATH
        if is_chatkit_alias and _chatkit_alias_is_sunset():
            logger.warning("chatkit.alias.sunset_enforced path=%s", request.url.path)
            return _attach_chatkit_alias_headers(
                _error_response(
                    request,
                    "DEPRECATED_ENDPOINT",
                    "POST /chatkit is no longer available; use POST /chat",
                    410,
                )
            )
        if is_chatkit_alias:
            logger.info("chatkit.alias.request path=%s sunset=%s", request.url.path, _CHATKIT_ALIAS_SUNSET_HTTP_DATE)

        token = request.app.state.config.auth_token
        if token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header != f"Bearer {token}":
                response = _error_response(request, "UNAUTHORIZED", "Authorization header is invalid", 401)
                return _attach_chatkit_alias_headers(response) if is_chatkit_alias else response

        tenant_id = (request.headers.get("X-Tenant-Id") or "").strip()
        if not tenant_id:
            response = _error_response(request, "ERR_TENANT_REQUIRED", "X-Tenant-Id header is required", 422)
            return _attach_chatkit_alias_headers(response) if is_chatkit_alias else response

        body = await request.body()
        metadata = {}
        request_type = ""
        try:
            parsed = json.loads(body.decode("utf-8"))
            request_type = str(parsed.get("type") or "").strip() if isinstance(parsed, dict) else ""
            metadata = parsed.get("metadata") or {} if isinstance(parsed, dict) else {}
        except Exception:
            metadata = {}
        metadata = dict(metadata)
        metadata["tenant_id"] = tenant_id
        metadata["correlation_id"] = _correlation_id(request)
        if request_type == "threads.create":
            header_project_id = (request.headers.get("X-Project-Id") or "").strip() or None
            try:
                resolved_scope = await resolve_thread_create_scope(
                    metadata,
                    header_project_id,
                    tenant_id,
                    resolve_project_default_workflow,
                )
            except ChatThreadResolutionError as exc:
                logger.warning(
                    "chatkit.thread_resolution mode=%s tenant_id=%s project_id=%s workflow_id=%s error_code=%s path=%s",
                    CHAT_RESOLUTION_MODE_ERROR,
                    tenant_id,
                    exc.project_id or metadata.get("project_id") or header_project_id or "",
                    exc.workflow_id or metadata.get("workflow_id") or "",
                    exc.code,
                    request.url.path,
                )
                response = _error_response(
                    request,
                    exc.code,
                    exc.message,
                    exc.status_code,
                    details=exc.details,
                )
                return _attach_chatkit_alias_headers(response) if is_chatkit_alias else response
            metadata["chat_resolution_mode"] = resolved_scope.mode
            if resolved_scope.project_id:
                metadata["project_id"] = resolved_scope.project_id
            metadata["workflow_id"] = resolved_scope.workflow_id
            if resolved_scope.workflow_version_id:
                metadata["workflow_version_id"] = resolved_scope.workflow_version_id
            logger.info(
                "chatkit.thread_resolution mode=%s tenant_id=%s project_id=%s workflow_id=%s workflow_version_id=%s path=%s",
                resolved_scope.mode,
                tenant_id,
                resolved_scope.project_id or "",
                resolved_scope.workflow_id,
                resolved_scope.workflow_version_id or "",
                request.url.path,
            )

        base_ctx = request.app.state.context
        ctx = ChatKitContext(
            service=base_ctx.service,
            run_store=base_ctx.run_store,
            idempotency=base_ctx.idempotency,
            tenant_id=tenant_id,
            request_metadata=metadata,
        )
        try:
            result = await request.app.state.server.process(body, ctx)
        except InvalidTranscriptionInputError as exc:
            response = _error_response(request, "ERR_INVALID_AUDIO_INPUT", str(exc), 422)
            return _attach_chatkit_alias_headers(response) if is_chatkit_alias else response
        except TranscriptionUnavailableError as exc:
            response = _error_response(request, "ERR_TRANSCRIPTION_UNAVAILABLE", str(exc), 503)
            return _attach_chatkit_alias_headers(response) if is_chatkit_alias else response

        if isinstance(result, StreamingResult):
            response = StreamingResponse(result, media_type="text/event-stream")
            return _attach_chatkit_alias_headers(response) if is_chatkit_alias else response
        if isinstance(result, NonStreamingResult):
            response = Response(result.json, media_type="application/json")
            return _attach_chatkit_alias_headers(response) if is_chatkit_alias else response
        response = Response(b"{}", media_type="application/json")
        return _attach_chatkit_alias_headers(response) if is_chatkit_alias else response

    async def health(_: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    routes = [
        Route("/health", health),
        Route(_CHAT_ENDPOINT_PATH, chatkit, methods=["POST"]),
        Route(_CHATKIT_ALIAS_PATH, chatkit, methods=["POST"]),
    ]

    app = Starlette(routes=routes, lifespan=lifespan)
    cors_origins = (
        get_env("CORS_ALLOW_ORIGINS")
        or "http://workcore.build:8080,https://workcore.build:8443,http://hq21.build,https://hq21.build"
    )
    allow_origins = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


app = create_service_app()
