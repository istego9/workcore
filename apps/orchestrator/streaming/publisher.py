from __future__ import annotations

from typing import Iterable

from apps.orchestrator.runtime.models import Event as RuntimeEvent

from .bus import EventBus
from .events import EventEnvelope, new_event_id, now_ts
from .store import EventStore


class EventPublisher:
    def __init__(self, store: EventStore, bus: EventBus) -> None:
        self.store = store
        self.bus = bus

    async def publish(self, events: Iterable[RuntimeEvent]) -> list[EventEnvelope]:
        published: list[EventEnvelope] = []
        for event in events:
            metadata = event.metadata or {}
            envelope = EventEnvelope(
                id=new_event_id(),
                type=event.type,
                run_id=event.run_id,
                workflow_id=event.workflow_id,
                version_id=event.version_id,
                node_id=event.node_id,
                payload=event.payload or {},
                timestamp=now_ts(),
                correlation_id=str(metadata.get("correlation_id")) if metadata.get("correlation_id") else None,
                trace_id=str(metadata.get("trace_id")) if metadata.get("trace_id") else None,
                tenant_id=str(metadata.get("tenant_id")) if metadata.get("tenant_id") else None,
                project_id=str(metadata.get("project_id")) if metadata.get("project_id") else None,
                import_run_id=str(metadata.get("import_run_id")) if metadata.get("import_run_id") else None,
            )
            envelope = await self.store.append(envelope)
            published.append(envelope)
            await self.bus.publish(envelope)
        return published
