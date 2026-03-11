from __future__ import annotations

from datetime import datetime, timezone
import json
import logging

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from chatkit.server import NonStreamingResult, StreamingResult

from apps.orchestrator.api.store import InMemoryRunStore
from apps.orchestrator.chatkit.context import ChatKitContext
from apps.orchestrator.chatkit.runtime_service import ChatKitRuntimeService
from apps.orchestrator.chatkit.server import (
    InvalidTranscriptionInputError,
    TranscriptionUnavailableError,
    WorkflowChatKitServer,
)
from apps.orchestrator.chatkit.scope_resolution import (
    CHAT_RESOLUTION_MODE_ERROR,
    ChatThreadResolutionError,
    resolve_thread_create_scope,
)
from apps.orchestrator.chatkit.store import InMemoryAttachmentStore, InMemoryChatKitStore
from apps.orchestrator.executors import IntegrationHTTPEgressPolicy, IntegrationHTTPExecutor, MCPExecutor, mcp_client_from_env
from apps.orchestrator.runtime.env import get_env
from apps.orchestrator.runtime import SimpleEvaluator
from apps.orchestrator.streaming import EventPublisher, InMemoryEventBus, InMemoryEventStore

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


def _normalize_bad_fields(value) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return None
    normalized = [
        str(item).strip()
        for item in value
        if isinstance(item, str) and str(item).strip()
    ]
    return normalized or None


def _default_bad_fields(code: str, message: str) -> list[str] | None:
    normalized_code = code.strip().upper()
    normalized_message = message.strip().lower()
    if normalized_code == "ERR_TENANT_REQUIRED":
        return ["X-Tenant-Id"]
    if normalized_code == "CHAT_PROJECT_SCOPE_REQUIRED":
        return ["metadata.project_id", "X-Project-Id"]
    if normalized_code == "ERR_INVALID_AUDIO_INPUT":
        if "mime" in normalized_message:
            return ["params.mime_type"]
        if "empty" in normalized_message or "audio payload" in normalized_message:
            return ["params.audio_base64"]
    return None


def _infer_category(code: str, status_code: int, unsupported_feature: str | None) -> str:
    normalized_code = code.strip().upper()
    if unsupported_feature:
        return "unsupported_feature"
    if normalized_code == "UNAUTHORIZED":
        return "auth"
    if normalized_code in {"CHAT_DEFAULT_WORKFLOW_NOT_CONFIGURED"}:
        return "configuration"
    if normalized_code in {"DEPRECATED_ENDPOINT"}:
        return "route"
    if normalized_code in {"ERR_TRANSCRIPTION_UNAVAILABLE"}:
        return "transient"
    if normalized_code in {"NOT_FOUND"} or normalized_code.endswith("NOT_FOUND"):
        return "not_found"
    if status_code in {401, 403}:
        return "auth"
    if status_code in {400, 422}:
        return "validation"
    if status_code == 404:
        return "not_found"
    if status_code in {429, 503}:
        return "transient"
    if status_code >= 500:
        return "internal"
    return "validation"


def _infer_retryable(category: str) -> bool | None:
    if category == "transient":
        return True
    if category in {
        "auth",
        "validation",
        "configuration",
        "not_found",
        "conflict",
        "unsupported_feature",
        "internal",
        "route",
        "action",
    }:
        return False
    return None


def _error_response(
    request: Request,
    code: str,
    message: str,
    status_code: int,
    *,
    category: str | None = None,
    retryable: bool | None = None,
    retry_after_s: int | None = None,
    bad_fields: list[str] | None = None,
    unsupported_feature: str | None = None,
    docs_ref: str | None = None,
    details=None,
) -> JSONResponse:
    correlation_id = _correlation_id(request)
    resolved_unsupported_feature = (
        unsupported_feature.strip()
        if isinstance(unsupported_feature, str) and unsupported_feature.strip()
        else (
            "input.transcribe"
            if code == "ERR_TRANSCRIPTION_UNAVAILABLE" and "not configured" in message.lower()
            else None
        )
    )
    resolved_bad_fields = _normalize_bad_fields(bad_fields) or _default_bad_fields(code, message)
    resolved_category = category or _infer_category(code, status_code, resolved_unsupported_feature)
    resolved_retryable = retryable if isinstance(retryable, bool) else _infer_retryable(resolved_category)
    resolved_retry_after_s = retry_after_s if isinstance(retry_after_s, int) and retry_after_s >= 0 else None
    error = {
        "code": code,
        "message": message,
        "category": resolved_category,
        "retryable": resolved_retryable,
        "retry_after_s": resolved_retry_after_s,
        "bad_fields": resolved_bad_fields,
        "unsupported_feature": resolved_unsupported_feature,
        "docs_ref": docs_ref,
        "details": details,
        "correlation_id": correlation_id,
    }
    response_headers: dict[str, str] = {}
    if resolved_retry_after_s is not None and status_code in {429, 503}:
        response_headers["Retry-After"] = str(resolved_retry_after_s)
    return JSONResponse(
        {"error": error, "correlation_id": correlation_id},
        status_code=status_code,
        headers=response_headers or None,
    )


def create_app(
    workflow,
    store: InMemoryChatKitStore | None = None,
    attachment_store: InMemoryAttachmentStore | None = None,
    run_store: InMemoryRunStore | None = None,
    transcriber=None,
    workflows: dict[str, object] | None = None,
    project_defaults: dict[str, str | None] | None = None,
) -> Starlette:
    chat_store = store or InMemoryChatKitStore()
    attachment_store = attachment_store or InMemoryAttachmentStore(chat_store.attachments)
    server = WorkflowChatKitServer(chat_store, attachment_store, transcriber=transcriber)
    workflow_registry = dict(workflows or {})
    workflow_registry.setdefault(workflow.id, workflow)
    project_default_registry = dict(project_defaults or {})

    event_store = InMemoryEventStore()
    event_bus = InMemoryEventBus()
    publisher = EventPublisher(event_store, event_bus)

    async def loader(workflow_id: str, version_id: str | None, tenant_id: str):
        if not tenant_id:
            raise RuntimeError("X-Tenant-Id is required")
        resolved_workflow = workflow_registry.get(workflow_id)
        if resolved_workflow is None:
            raise RuntimeError("Unknown workflow_id")
        return resolved_workflow

    async def resolve_project_default_workflow(project_id: str, tenant_id: str) -> tuple[str, str | None]:
        if not tenant_id:
            raise ChatThreadResolutionError("ERR_TENANT_REQUIRED", "X-Tenant-Id header is required", 422)
        if project_id not in project_default_registry:
            raise ChatThreadResolutionError("ERR_PROJECT_NOT_FOUND", "project not found", 404, project_id=project_id)
        default_workflow_id = project_default_registry.get(project_id)
        if not isinstance(default_workflow_id, str) or not default_workflow_id.strip():
            raise ChatThreadResolutionError(
                "CHAT_DEFAULT_WORKFLOW_NOT_CONFIGURED",
                "project default chat workflow is not configured",
                409,
                project_id=project_id,
            )
        resolved_workflow = workflow_registry.get(default_workflow_id.strip())
        if resolved_workflow is None or not getattr(resolved_workflow, "version_id", ""):
            raise ChatThreadResolutionError(
                "CHAT_DEFAULT_WORKFLOW_NOT_FOUND",
                "project default chat workflow is missing or not published",
                404,
                project_id=project_id,
                workflow_id=default_workflow_id.strip(),
            )
        return default_workflow_id.strip(), str(resolved_workflow.version_id)

    integration_http_policy = IntegrationHTTPEgressPolicy.from_env(get_env)
    runtime = ChatKitRuntimeService(
        publisher=publisher,
        store=event_store,
        bus=event_bus,
        evaluator=SimpleEvaluator(),
        workflow_loader=loader,
        executors={
            "integration_http": IntegrationHTTPExecutor(egress_policy=integration_http_policy),
            "mcp": MCPExecutor(mcp_client_from_env(get_env)),
        },
    )

    base_run_store = run_store or InMemoryRunStore()

    async def chatkit(request: Request):
        is_chatkit_alias = request.url.path == _CHATKIT_ALIAS_PATH
        if is_chatkit_alias and _chatkit_alias_is_sunset():
            logger.warning("chatkit.alias.sunset_enforced path=%s", request.url.path)
            return _attach_chatkit_alias_headers(
                _error_response(
                    request,
                    "DEPRECATED_ENDPOINT",
                    "POST /chatkit is no longer available; use POST /chat",
                    status_code=410,
                )
            )
        if is_chatkit_alias:
            logger.info("chatkit.alias.request path=%s sunset=%s", request.url.path, _CHATKIT_ALIAS_SUNSET_HTTP_DATE)

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

        ctx = ChatKitContext(
            service=runtime,
            run_store=base_run_store,
            tenant_id=tenant_id,
            request_metadata=metadata,
        )
        try:
            result = await server.process(body, ctx)
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

    routes = [
        Route(_CHAT_ENDPOINT_PATH, chatkit, methods=["POST"]),
        Route(_CHATKIT_ALIAS_PATH, chatkit, methods=["POST"]),
    ]
    return Starlette(routes=routes)
