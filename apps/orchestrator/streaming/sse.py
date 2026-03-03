from __future__ import annotations

import asyncio
from inspect import isawaitable
from typing import AsyncIterator, Awaitable, Callable, Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route

from .bus import EventBus
from .events import EventEnvelope
from .store import EventStore


SnapshotProvider = Callable[[str], Optional[EventEnvelope] | Awaitable[Optional[EventEnvelope]]]


async def _event_stream(
    run_id: str,
    store: EventStore,
    bus: EventBus,
    last_event_id: Optional[str],
    snapshot_provider: Optional[SnapshotProvider],
) -> AsyncIterator[str]:
    seen = set()
    replay_after_id = last_event_id

    if not last_event_id and snapshot_provider:
        snapshot = snapshot_provider(run_id)
        if isawaitable(snapshot):
            snapshot = await snapshot
        if snapshot:
            seen.add(snapshot.id)
            yield _format_sse(snapshot)
            payload = snapshot.payload if isinstance(snapshot.payload, dict) else {}
            last_snapshot_event_id = payload.get("last_event_id")
            if isinstance(last_snapshot_event_id, str) and last_snapshot_event_id:
                replay_after_id = last_snapshot_event_id

    replay = await store.list_events(run_id, after_id=replay_after_id)
    for event in replay:
        seen.add(event.id)
        yield _format_sse(event)

    async for event in bus.subscribe(run_id):
        if event.id in seen:
            continue
        yield _format_sse(event)


def _format_sse(event: EventEnvelope) -> str:
    payload = event.to_sse()
    return "\n".join(
        [
            f"id: {payload['id']}",
            f"event: {payload['event']}",
            f"data: {payload['data']}",
            "",
        ]
    )


def create_app(
    store: EventStore,
    bus: EventBus,
    snapshot_provider: Optional[SnapshotProvider] = None,
) -> Starlette:
    async def stream(request: Request) -> StreamingResponse:
        run_id = request.path_params["run_id"]
        last_event_id = request.headers.get("Last-Event-ID")
        generator = _event_stream(run_id, store, bus, last_event_id, snapshot_provider)
        return StreamingResponse(generator, media_type="text/event-stream")

    routes = [
        Route("/runs/{run_id}/stream", stream),
    ]
    return Starlette(routes=routes)
