from __future__ import annotations

from contextlib import asynccontextmanager
import json
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
from apps.orchestrator.chatkit.config import ChatKitConfig
from apps.orchestrator.chatkit.context import ChatKitContext
from apps.orchestrator.chatkit.idempotency import IdempotencyStore
from apps.orchestrator.chatkit.runtime_service import ChatKitRuntimeService
from apps.orchestrator.chatkit.object_store import MinioAttachmentStore
from apps.orchestrator.chatkit.pg_store import PostgresChatKitStore
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
from apps.orchestrator.runtime import Edge, Node, SimpleEvaluator, Workflow, CelEvaluator
from apps.orchestrator.streaming import EventPublisher, InMemoryEventBus, InMemoryEventStore
from apps.orchestrator.runtime.env import get_env


def _audio_filename_from_media_type(media_type: str) -> str:
    normalized = media_type.strip().lower()
    if normalized == "audio/ogg":
        return "input.ogg"
    if normalized == "audio/mp4":
        return "input.m4a"
    return "input.webm"


def _build_transcriber(cfg: ChatKitConfig):
    api_key = cfg.stt_api_key
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
            return JSONResponse(
                {"error": {"code": "ERR_INVALID_AUDIO_INPUT", "message": str(exc)}},
                status_code=422,
            )
        except TranscriptionUnavailableError as exc:
            return JSONResponse(
                {"error": {"code": "ERR_TRANSCRIPTION_UNAVAILABLE", "message": str(exc)}},
                status_code=503,
            )
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
