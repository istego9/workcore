from __future__ import annotations

import json

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from chatkit.server import NonStreamingResult, StreamingResult

from apps.orchestrator.api.store import InMemoryRunStore
from apps.orchestrator.chatkit.context import ChatKitContext
from apps.orchestrator.chatkit.runtime_service import ChatKitRuntimeService
from apps.orchestrator.chatkit.server import WorkflowChatKitServer
from apps.orchestrator.chatkit.store import InMemoryAttachmentStore, InMemoryChatKitStore
from apps.orchestrator.runtime import SimpleEvaluator
from apps.orchestrator.streaming import EventPublisher, InMemoryEventBus, InMemoryEventStore


def create_app(
    workflow,
    store: InMemoryChatKitStore | None = None,
    attachment_store: InMemoryAttachmentStore | None = None,
    run_store: InMemoryRunStore | None = None,
) -> Starlette:
    chat_store = store or InMemoryChatKitStore()
    attachment_store = attachment_store or InMemoryAttachmentStore(chat_store.attachments)
    server = WorkflowChatKitServer(chat_store, attachment_store)

    event_store = InMemoryEventStore()
    event_bus = InMemoryEventBus()
    publisher = EventPublisher(event_store, event_bus)

    async def loader(workflow_id: str, version_id: str | None, tenant_id: str):
        if not tenant_id:
            raise RuntimeError("X-Tenant-Id is required")
        if workflow_id != workflow.id:
            raise RuntimeError("Unknown workflow_id")
        return workflow

    runtime = ChatKitRuntimeService(
        publisher=publisher,
        store=event_store,
        bus=event_bus,
        evaluator=SimpleEvaluator(),
        workflow_loader=loader,
    )

    base_run_store = run_store or InMemoryRunStore()

    async def chatkit(request: Request):
        tenant_id = (request.headers.get("X-Tenant-Id") or "").strip()
        if not tenant_id:
            return JSONResponse(
                {"error": {"code": "ERR_TENANT_REQUIRED", "message": "X-Tenant-Id header is required"}},
                status_code=422,
            )
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
        result = await server.process(body, ctx)
        if isinstance(result, StreamingResult):
            return StreamingResponse(result, media_type="text/event-stream")
        if isinstance(result, NonStreamingResult):
            return Response(result.json, media_type="application/json")
        return Response(b"{}", media_type="application/json")

    routes = [Route("/chatkit", chatkit, methods=["POST"])]
    return Starlette(routes=routes)
