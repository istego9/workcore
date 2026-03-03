from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from apps.orchestrator.runtime import OrchestratorEngine
from apps.orchestrator.runtime.models import Event as RuntimeEvent, Run, Workflow
from apps.orchestrator.runtime.projection import project_run_payload_for_transport
from apps.orchestrator.streaming import (
    EventPublisher,
    InMemoryEventBus,
    EventStore,
    EventEnvelope,
    new_event_id,
    now_ts,
)


WorkflowLoader = Callable[[str, Optional[str], str], Awaitable[Workflow]]


@dataclass
class ChatKitRuntimeService:
    publisher: EventPublisher
    store: EventStore
    bus: InMemoryEventBus
    evaluator: Any
    workflow_loader: WorkflowLoader
    executors: Dict[str, Any] = field(default_factory=dict)

    async def start_run(
        self,
        workflow_id: str,
        version_id: Optional[str],
        inputs: Dict[str, Any],
        tenant_id: str,
        mode: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Run:
        if not tenant_id:
            raise RuntimeError("tenant_id is required")
        workflow = await self.workflow_loader(workflow_id, version_id, tenant_id)
        engine = OrchestratorEngine(workflow, self.evaluator, self.executors)
        metadata_payload = dict(metadata or {})
        if mode == "live":
            metadata_payload.setdefault("agent_executor_mode", "live")
            metadata_payload.setdefault("agent_mock", False)
            metadata_payload.setdefault("llm_enabled", True)
        elif mode == "test":
            metadata_payload.setdefault("agent_executor_mode", "mock")
            metadata_payload.setdefault("agent_mock", True)
            metadata_payload.setdefault("llm_enabled", False)
        metadata_payload["tenant_id"] = tenant_id
        run = engine.start_run(inputs, mode=mode, metadata=metadata_payload)
        events = await asyncio.to_thread(engine.execute_until_blocked, run)
        await self._publish_with_snapshot(run, events)
        return run

    async def resume_interrupt(
        self,
        run: Run,
        interrupt_id: str,
        input_data: Optional[Dict[str, Any]] = None,
        files: Optional[list] = None,
        tenant_id: Optional[str] = None,
    ) -> Run:
        resolved_tenant = tenant_id or str((run.metadata or {}).get("tenant_id") or "")
        if not resolved_tenant:
            raise RuntimeError("tenant_id is required")
        workflow = await self.workflow_loader(run.workflow_id, run.version_id, resolved_tenant)
        engine = OrchestratorEngine(workflow, self.evaluator, self.executors)
        events = await asyncio.to_thread(engine.resume_interrupt, run, interrupt_id, input_data, files)
        await self._publish_with_snapshot(run, events)
        return run

    async def _publish_with_snapshot(self, run: Run, events: list[RuntimeEvent]) -> None:
        published = await self.publisher.publish(events)
        last_event = published[-1] if published else await self.store.last_event(run.id)
        last_event_id = last_event.id if last_event else None
        last_sequence = last_event.sequence if last_event else await self.store.last_sequence(run.id)
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
        await self.store.set_snapshot(run.id, snapshot)
