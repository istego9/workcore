from __future__ import annotations

import asyncio
from dataclasses import dataclass
from inspect import Parameter, signature
from typing import Any, Awaitable, Callable, Dict, Optional

from apps.orchestrator.runtime.engine import OrchestratorEngine
from apps.orchestrator.runtime.evaluator import CelEvaluator, SimpleEvaluator
from apps.orchestrator.runtime.models import Event as RuntimeEvent, Run, Workflow
from apps.orchestrator.runtime.projection import project_run_payload_for_transport
from apps.orchestrator.streaming import (
    EventEnvelope,
    EventPublisher,
    InMemoryEventBus,
    InMemoryEventStore,
    KafkaConfig,
    KafkaEventBus,
    new_event_id,
    now_ts,
)

from .config import RuntimeConfig


WorkflowLoader = Callable[..., Awaitable[Workflow]]
CapabilityResolver = Callable[[str, str, str], Awaitable[Optional[Dict[str, Any]]]]


@dataclass
class MultiWorkflowRuntimeService:
    publisher: EventPublisher
    store: InMemoryEventStore
    bus: object
    evaluator: Any
    workflow_loader: WorkflowLoader
    executors: Dict[str, Any]
    event_hook: Optional[Callable[[Run, list[RuntimeEvent]], Awaitable[None]]] = None
    resolve_capability: Optional[CapabilityResolver] = None

    @classmethod
    def create(
        cls,
        workflow_loader: WorkflowLoader,
        config: Optional[RuntimeConfig] = None,
        evaluator: Any | None = None,
        executors: Optional[Dict[str, Any]] = None,
        resolve_capability: Optional[CapabilityResolver] = None,
    ) -> "MultiWorkflowRuntimeService":
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
        if evaluator is None:
            try:
                evaluator = CelEvaluator()
            except Exception:
                evaluator = SimpleEvaluator()
        return cls(
            publisher=publisher,
            store=store,
            bus=bus,
            evaluator=evaluator,
            workflow_loader=workflow_loader,
            executors=executors or {},
            resolve_capability=resolve_capability,
        )

    async def startup(self) -> None:
        if isinstance(self.bus, KafkaEventBus):
            await self.bus.start()

    async def shutdown(self) -> None:
        if isinstance(self.bus, KafkaEventBus):
            await self.bus.stop()

    async def start_run(
        self,
        workflow_id: str,
        version_id: Optional[str],
        inputs: Dict[str, Any],
        mode: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Run:
        tenant_id = None
        if isinstance(metadata, dict):
            value = metadata.get("tenant_id")
            if isinstance(value, str) and value:
                tenant_id = value
        workflow = await self._load_workflow(workflow_id, version_id, tenant_id=tenant_id)
        run_metadata = dict(metadata or {})
        capability_bindings = await self._resolve_capability_bindings(workflow, tenant_id=tenant_id)
        if capability_bindings:
            run_metadata["capability_bindings"] = capability_bindings
        engine = OrchestratorEngine(workflow, self.evaluator, self.executors)
        run = engine.start_run(inputs, mode=mode, metadata=run_metadata)
        events = await asyncio.to_thread(engine.execute_until_blocked, run)
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
        tenant_id = None
        value = (run.metadata or {}).get("tenant_id")
        if isinstance(value, str) and value:
            tenant_id = value
        workflow = await self._load_workflow(run.workflow_id, run.version_id, tenant_id=tenant_id)
        capability_bindings = await self._resolve_capability_bindings(workflow, tenant_id=tenant_id)
        if capability_bindings:
            run.metadata = dict(run.metadata or {})
            run.metadata.setdefault("capability_bindings", capability_bindings)
        engine = OrchestratorEngine(workflow, self.evaluator, self.executors)
        events = await asyncio.to_thread(engine.resume_interrupt, run, interrupt_id, input_data, files)
        await self._publish_with_snapshot(run, events)
        await self._notify_hooks(run, events)
        return run

    async def rerun_node(self, run: Run, node_id: str, scope: str) -> Run:
        tenant_id = None
        value = (run.metadata or {}).get("tenant_id")
        if isinstance(value, str) and value:
            tenant_id = value
        workflow = await self._load_workflow(run.workflow_id, run.version_id, tenant_id=tenant_id)
        capability_bindings = await self._resolve_capability_bindings(workflow, tenant_id=tenant_id)
        if capability_bindings:
            run.metadata = dict(run.metadata or {})
            run.metadata.setdefault("capability_bindings", capability_bindings)
        engine = OrchestratorEngine(workflow, self.evaluator, self.executors)
        await asyncio.to_thread(engine.rerun_node, run, node_id, scope)
        events = await asyncio.to_thread(engine.execute_until_blocked, run)
        await self._publish_with_snapshot(run, events)
        await self._notify_hooks(run, events)
        return run

    async def _load_workflow(
        self,
        workflow_id: str,
        version_id: Optional[str],
        tenant_id: Optional[str] = None,
    ) -> Workflow:
        if tenant_id and self._loader_accepts_tenant():
            if self._loader_accepts_tenant_keyword():
                return await self.workflow_loader(workflow_id, version_id, tenant_id=tenant_id)
            return await self.workflow_loader(workflow_id, version_id, tenant_id)
        return await self.workflow_loader(workflow_id, version_id)

    def _loader_accepts_tenant(self) -> bool:
        try:
            params = list(signature(self.workflow_loader).parameters.values())
        except (TypeError, ValueError):
            return False
        if any(param.kind is Parameter.VAR_KEYWORD for param in params):
            return True
        positional = [
            param
            for param in params
            if param.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
        ]
        return len(positional) >= 3

    def _loader_accepts_tenant_keyword(self) -> bool:
        try:
            params = signature(self.workflow_loader).parameters
        except (TypeError, ValueError):
            return False
        if "tenant_id" in params:
            return True
        return any(param.kind is Parameter.VAR_KEYWORD for param in params.values())

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
        if self.event_hook:
            await self.event_hook(run, events)

    async def _resolve_capability_bindings(
        self,
        workflow: Workflow,
        tenant_id: Optional[str],
    ) -> Dict[str, Dict[str, str]]:
        bindings: Dict[str, Dict[str, str]] = {}
        for node in workflow.nodes.values():
            config = node.config if isinstance(node.config, dict) else {}
            capability_id = config.get("capability_id")
            capability_version = config.get("capability_version")
            cap_id = capability_id.strip() if isinstance(capability_id, str) else ""
            cap_version = capability_version.strip() if isinstance(capability_version, str) else ""
            if bool(cap_id) != bool(cap_version):
                raise ValueError(
                    f"node {node.id} capability pin requires both capability_id and capability_version"
                )
            if not cap_id:
                continue
            bindings[node.id] = {"capability_id": cap_id, "capability_version": cap_version}
            if self.resolve_capability is None:
                continue
            tenant = tenant_id or "local"
            contract = await self.resolve_capability(tenant, cap_id, cap_version)
            if contract is None:
                raise ValueError(f"capability {cap_id}@{cap_version} not found for node {node.id}")
            self._apply_capability_contract_defaults(node, contract)
        return bindings

    @staticmethod
    def _apply_capability_contract_defaults(node, contract: Dict[str, Any]) -> None:
        if not isinstance(node.config, dict) or not isinstance(contract, dict):
            return
        constraints = contract.get("constraints")
        if not isinstance(constraints, dict):
            constraints = {}
        timeout_value = constraints.get("timeout_s", contract.get("timeout_s"))
        if node.config.get("timeout_s") is None and isinstance(timeout_value, (int, float)):
            node.config["timeout_s"] = float(timeout_value)

        retry_policy = contract.get("retry_policy")
        if not isinstance(retry_policy, dict):
            retry_policy = {}
        max_retries = retry_policy.get("max_retries")
        if node.config.get("max_retries") is None and isinstance(max_retries, int):
            node.config["max_retries"] = max_retries
