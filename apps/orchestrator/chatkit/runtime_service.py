from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from apps.orchestrator.runtime import OrchestratorEngine
from apps.orchestrator.runtime.models import Event as RuntimeEvent, Run, Workflow
from apps.orchestrator.streaming import (
    EventPublisher,
    InMemoryEventBus,
    InMemoryEventStore,
    EventEnvelope,
    new_event_id,
    now_ts,
)


WorkflowLoader = Callable[[str, Optional[str]], Awaitable[Workflow]]


@dataclass
class ChatKitRuntimeService:
    publisher: EventPublisher
    store: InMemoryEventStore
    bus: InMemoryEventBus
    evaluator: Any
    workflow_loader: WorkflowLoader
    executors: Dict[str, Any] = field(default_factory=dict)

    async def start_run(
        self,
        workflow_id: str,
        version_id: Optional[str],
        inputs: Dict[str, Any],
        mode: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Run:
        workflow = await self.workflow_loader(workflow_id, version_id)
        engine = OrchestratorEngine(workflow, self.evaluator, self.executors)
        run = engine.start_run(inputs, mode=mode, metadata=metadata)
        events = engine.execute_until_blocked(run)
        await self._publish_with_snapshot(run, events)
        return run

    async def resume_interrupt(
        self,
        run: Run,
        interrupt_id: str,
        input_data: Optional[Dict[str, Any]] = None,
        files: Optional[list] = None,
    ) -> Run:
        workflow = await self.workflow_loader(run.workflow_id, run.version_id)
        engine = OrchestratorEngine(workflow, self.evaluator, self.executors)
        events = engine.resume_interrupt(run, interrupt_id, input_data, files)
        await self._publish_with_snapshot(run, events)
        return run

    async def _publish_with_snapshot(self, run: Run, events: list[RuntimeEvent]) -> None:
        published = await self.publisher.publish(events)
        last_event = published[-1] if published else self.store.last_event(run.id)
        last_event_id = last_event.id if last_event else None
        last_sequence = last_event.sequence if last_event else self.store.last_sequence(run.id)
        run_metadata = run.metadata or {}
        snapshot = EventEnvelope(
            id=new_event_id(),
            type="snapshot",
            run_id=run.id,
            workflow_id=run.workflow_id,
            version_id=run.version_id,
            node_id=None,
            payload={
                "status": run.status,
                "state": run.state,
                "outputs": run.outputs,
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
