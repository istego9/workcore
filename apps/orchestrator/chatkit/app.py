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


def create_app(
    workflow,
    store: InMemoryChatKitStore | None = None,
    attachment_store: InMemoryAttachmentStore | None = None,
    run_store: InMemoryRunStore | None = None,
    transcriber=None,
) -> Starlette:
    chat_store = store or InMemoryChatKitStore()
    attachment_store = attachment_store or InMemoryAttachmentStore(chat_store.attachments)
    server = WorkflowChatKitServer(chat_store, attachment_store, transcriber=transcriber)

    event_store = InMemoryEventStore()
    event_bus = InMemoryEventBus()
    publisher = EventPublisher(event_store, event_bus)

    async def loader(workflow_id: str, version_id: str | None, tenant_id: str):
        if not tenant_id:
            raise RuntimeError("X-Tenant-Id is required")
        if workflow_id != workflow.id:
            raise RuntimeError("Unknown workflow_id")
        return workflow

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
                JSONResponse(
                    {
                        "error": {
                            "code": "DEPRECATED_ENDPOINT",
                            "message": "POST /chatkit is no longer available; use POST /chat",
                        }
                    },
                    status_code=410,
                )
            )
        if is_chatkit_alias:
            logger.info("chatkit.alias.request path=%s sunset=%s", request.url.path, _CHATKIT_ALIAS_SUNSET_HTTP_DATE)

        tenant_id = (request.headers.get("X-Tenant-Id") or "").strip()
        if not tenant_id:
            response = JSONResponse(
                {"error": {"code": "ERR_TENANT_REQUIRED", "message": "X-Tenant-Id header is required"}},
                status_code=422,
            )
            return _attach_chatkit_alias_headers(response) if is_chatkit_alias else response
        body = await request.body()
        metadata = {}
        try:
            parsed = json.loads(body.decode("utf-8"))
            metadata = parsed.get("metadata") or {}
        except Exception:
            metadata = {}
        metadata = dict(metadata)
        metadata["tenant_id"] = tenant_id

        ctx = ChatKitContext(
            service=runtime,
            run_store=base_run_store,
            tenant_id=tenant_id,
            request_metadata=metadata,
        )
        try:
            result = await server.process(body, ctx)
        except InvalidTranscriptionInputError as exc:
            response = JSONResponse(
                {"error": {"code": "ERR_INVALID_AUDIO_INPUT", "message": str(exc)}},
                status_code=422,
            )
            return _attach_chatkit_alias_headers(response) if is_chatkit_alias else response
        except TranscriptionUnavailableError as exc:
            response = JSONResponse(
                {"error": {"code": "ERR_TRANSCRIPTION_UNAVAILABLE", "message": str(exc)}},
                status_code=503,
            )
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
