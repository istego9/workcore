from __future__ import annotations

from contextlib import asynccontextmanager
import json
from typing import Any

import asyncpg
from minio import Minio
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route

from chatkit.server import NonStreamingResult, StreamingResult

from apps.orchestrator.api.store import PostgresRunStore
from apps.orchestrator.chatkit.config import ChatKitConfig
from apps.orchestrator.chatkit.context import ChatKitContext
from apps.orchestrator.chatkit.idempotency import IdempotencyStore
from apps.orchestrator.chatkit.runtime_service import ChatKitRuntimeService
from apps.orchestrator.chatkit.object_store import MinioAttachmentStore
from apps.orchestrator.chatkit.pg_store import PostgresChatKitStore
from apps.orchestrator.chatkit.server import WorkflowChatKitServer
from apps.orchestrator.executors import AGENTS_AVAILABLE, AgentExecutor, MockAgentExecutor
from apps.orchestrator.runtime import Edge, Node, SimpleEvaluator, Workflow, CelEvaluator
from apps.orchestrator.streaming import EventPublisher, InMemoryEventBus, InMemoryEventStore
from apps.orchestrator.runtime.env import get_env


async def load_workflow_from_db(
    pool: asyncpg.Pool,
    workflow_id: str,
    version_id: str | None = None,
) -> Workflow:
    if version_id:
        row = await pool.fetchrow(
            "select id, content from workflow_versions where id = $1 and workflow_id = $2",
            version_id,
            workflow_id,
        )
    else:
        workflow_row = await pool.fetchrow(
            "select active_version_id from workflows where id = $1",
            workflow_id,
        )
        active_version_id = workflow_row["active_version_id"] if workflow_row else None
        if active_version_id:
            row = await pool.fetchrow(
                "select id, content from workflow_versions where id = $1",
                active_version_id,
            )
        else:
            row = await pool.fetchrow(
                """
                select id, content
                from workflow_versions
                where workflow_id = $1
                order by version_number desc
                limit 1
                """,
                workflow_id,
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

        async def loader(workflow_id: str, version_id: str | None) -> Workflow:
            return await load_workflow_from_db(pool, workflow_id, version_id)

        executor_mode = (get_env("AGENT_EXECUTOR_MODE") or "").lower()
        executors: dict[str, Any] = {}
        if executor_mode == "mock":
            executors["agent"] = MockAgentExecutor()
        elif AGENTS_AVAILABLE:
            executors["agent"] = AgentExecutor()

        service = ChatKitRuntimeService(
            publisher=publisher,
            store=event_store,
            bus=event_bus,
            evaluator=evaluator,
            workflow_loader=loader,
            executors=executors,
        )

        app.state.server = WorkflowChatKitServer(store, attachment_store)
        app.state.context = ChatKitContext(
            service=service,
            run_store=PostgresRunStore(pool),
            idempotency=idempotency,
        )
        app.state.pool = pool
        app.state.service = service
        app.state.config = cfg

        try:
            yield
        finally:
            await pool.close()

    async def chatkit(request: Request):
        token = request.app.state.config.auth_token
        if token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header != f"Bearer {token}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)

        body = await request.body()
        metadata = {}
        try:
            parsed = json.loads(body.decode("utf-8"))
            metadata = parsed.get("metadata") or {}
        except Exception:
            metadata = {}

        base_ctx = request.app.state.context
        ctx = ChatKitContext(
            service=base_ctx.service,
            run_store=base_ctx.run_store,
            idempotency=base_ctx.idempotency,
            request_metadata=metadata,
        )
        result = await request.app.state.server.process(body, ctx)
        if isinstance(result, StreamingResult):
            return StreamingResponse(result, media_type="text/event-stream")
        if isinstance(result, NonStreamingResult):
            return Response(result.json, media_type="application/json")
        return Response(b"{}", media_type="application/json")

    async def health(_: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    routes = [
        Route("/health", health),
        Route("/chatkit", chatkit, methods=["POST"]),
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
