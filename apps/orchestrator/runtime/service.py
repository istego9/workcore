from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

from apps.orchestrator.runtime.engine import OrchestratorEngine
from apps.orchestrator.runtime.models import Event as RuntimeEvent, Run
from apps.orchestrator.streaming import (
    EventPublisher,
    InMemoryEventBus,
    InMemoryEventStore,
    KafkaConfig,
    KafkaEventBus,
    EventEnvelope,
    now_ts,
    new_event_id,
)
from apps.orchestrator.runtime.projection import project_run_payload_for_transport

from .config import RuntimeConfig


@dataclass
class OrchestratorService:
    engine: OrchestratorEngine
    publisher: EventPublisher
    store: InMemoryEventStore
    bus: object

    @classmethod
    def create(cls, engine: OrchestratorEngine, config: Optional[RuntimeConfig] = None) -> "OrchestratorService":
        cfg = config or RuntimeConfig.from_env()
        store = InMemoryEventStore()
        if cfg.streaming.backend == "kafka":
            bus = KafkaEventBus(
                KafkaConfig(
                    bootstrap_servers=cfg.streaming.kafka_bootstrap_servers,
                    topic=cfg.streaming.kafka_topic,
                    group_id=cfg.streaming.kafka_group_id,
                )
            )
        else:
            bus = InMemoryEventBus()
        publisher = EventPublisher(store, bus)
        return cls(engine=engine, publisher=publisher, store=store, bus=bus)

    async def startup(self) -> None:
        if isinstance(self.bus, KafkaEventBus):
            await self.bus.start()

    async def shutdown(self) -> None:
        if isinstance(self.bus, KafkaEventBus):
            await self.bus.stop()

    async def start_run(
        self,
        inputs: Dict[str, Any],
        mode: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Run:
        run = self.engine.start_run(inputs, mode=mode, metadata=metadata)
        events = await asyncio.to_thread(self.engine.execute_until_blocked, run)
        await self._publish_with_snapshot(run, events)
        await self._notify_hooks(run, events)
        return run

    async def resume_interrupt(
        self,
        run: Run,
        interrupt_id: str,
        input_data: Optional[Dict[str, Any]] = None,
        files: Optional[list] = None,
    ) -> Run:
        events = await asyncio.to_thread(self.engine.resume_interrupt, run, interrupt_id, input_data, files)
        await self._publish_with_snapshot(run, events)
        await self._notify_hooks(run, events)
        return run

    async def rerun_node(self, run: Run, node_id: str, scope: str) -> Run:
        await asyncio.to_thread(self.engine.rerun_node, run, node_id, scope)
        events = await asyncio.to_thread(self.engine.execute_until_blocked, run)
        await self._publish_with_snapshot(run, events)
        await self._notify_hooks(run, events)
        return run

    async def _publish_with_snapshot(self, run: Run, events: list[RuntimeEvent]) -> None:
        published = await self.publisher.publish(events)
        last_event = published[-1] if published else self.store.last_event(run.id)
        last_event_id = last_event.id if last_event else None
        last_sequence = last_event.sequence if last_event else self.store.last_sequence(run.id)
        run_metadata = run.metadata or {}
        projected_state, projected_outputs = project_run_payload_for_transport(run.state, run.outputs, run_metadata)
        snapshot = EventEnvelope(
            id=new_event_id(),
            type="snapshot",
            run_id=run.id,
            workflow_id=run.workflow_id,
            version_id=run.version_id,
            node_id=None,
            payload={
                "status": run.status,
                "state": projected_state,
                "outputs": projected_outputs,
                "node_runs": {nid: nr.status for nid, nr in run.node_runs.items()},
                "mode": run.mode,
                "metadata": run_metadata,
                "last_event_id": last_event_id,
                "last_sequence": last_sequence,
            },
            timestamp=now_ts(),
            sequence=last_sequence,
            correlation_id=str(run_metadata.get("correlation_id")) if run_metadata.get("correlation_id") else None,
            trace_id=str(run_metadata.get("trace_id")) if run_metadata.get("trace_id") else None,
            tenant_id=str(run_metadata.get("tenant_id")) if run_metadata.get("tenant_id") else None,
            project_id=str(run_metadata.get("project_id")) if run_metadata.get("project_id") else None,
            import_run_id=str(run_metadata.get("import_run_id")) if run_metadata.get("import_run_id") else None,
        )
        self.store.set_snapshot(run.id, snapshot)

    async def _notify_hooks(self, run: Run, events: list[RuntimeEvent]) -> None:
        hook = getattr(self, "event_hook", None)
        if hook:
            await hook(run, events)

    def sse_app(self):
        from apps.orchestrator.streaming.sse import create_app

        return create_app(self.store, self.bus, snapshot_provider=self.store.get_snapshot)
