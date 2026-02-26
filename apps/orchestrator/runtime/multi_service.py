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

        node_type = getattr(node, "type", "")
        if node_type == "mcp":
            defaults = MultiWorkflowRuntimeService._extract_data_source_defaults(contract, constraints, "mcp")
            MultiWorkflowRuntimeService._apply_mcp_defaults(node.config, defaults)
        elif node_type == "integration_http":
            defaults = MultiWorkflowRuntimeService._extract_data_source_defaults(
                contract,
                constraints,
                "integration_http",
            )
            MultiWorkflowRuntimeService._apply_integration_http_defaults(node.config, defaults)

    @staticmethod
    def _extract_data_source_defaults(
        contract: Dict[str, Any],
        constraints: Dict[str, Any],
        node_type: str,
    ) -> Dict[str, Any]:
        defaults: Dict[str, Any] = {}
        constraints_key = f"{node_type}_defaults"
        constraints_defaults = constraints.get(constraints_key)
        if isinstance(constraints_defaults, dict):
            defaults.update(constraints_defaults)

        compatibility_defaults = contract.get("data_source_defaults")
        if isinstance(compatibility_defaults, dict):
            compat_node_defaults = compatibility_defaults.get(node_type)
            if isinstance(compat_node_defaults, dict):
                for key, value in compat_node_defaults.items():
                    defaults.setdefault(key, value)
        return defaults

    @staticmethod
    def _apply_mcp_defaults(node_config: Dict[str, Any], defaults: Dict[str, Any]) -> None:
        if not isinstance(defaults, dict) or not defaults:
            return

        for key in ("server", "tool"):
            value = defaults.get(key)
            if isinstance(value, str) and value.strip() and MultiWorkflowRuntimeService._is_missing(node_config.get(key)):
                node_config[key] = value.strip()

        timeout_value = defaults.get("timeout_s")
        if MultiWorkflowRuntimeService._is_missing(node_config.get("timeout_s")) and isinstance(timeout_value, (int, float)):
            node_config["timeout_s"] = float(timeout_value)

        arguments_value = defaults.get("arguments")
        if MultiWorkflowRuntimeService._is_missing(node_config.get("arguments")) and isinstance(arguments_value, dict):
            node_config["arguments"] = dict(arguments_value)

        allowed_tools_value = defaults.get("allowed_tools")
        if MultiWorkflowRuntimeService._is_missing(node_config.get("allowed_tools")) and isinstance(allowed_tools_value, list):
            tools = [item.strip() for item in allowed_tools_value if isinstance(item, str) and item.strip()]
            node_config["allowed_tools"] = tools

        auth_value = defaults.get("auth")
        if MultiWorkflowRuntimeService._is_missing(node_config.get("auth")) and isinstance(auth_value, dict):
            node_config["auth"] = MultiWorkflowRuntimeService._sanitize_auth_defaults(auth_value)

    @staticmethod
    def _apply_integration_http_defaults(node_config: Dict[str, Any], defaults: Dict[str, Any]) -> None:
        if not isinstance(defaults, dict) or not defaults:
            return

        for key in (
            "url",
            "method",
            "request_body_expression",
            "response_state_target",
            "response_body_state_target",
        ):
            value = defaults.get(key)
            if isinstance(value, str) and value.strip() and MultiWorkflowRuntimeService._is_missing(node_config.get(key)):
                node_config[key] = value.strip()

        for key in ("timeout_s", "retry_attempts", "retry_backoff_s"):
            value = defaults.get(key)
            if MultiWorkflowRuntimeService._is_missing(node_config.get(key)) and isinstance(value, (int, float)):
                node_config[key] = value

        if "fail_on_status" in defaults and MultiWorkflowRuntimeService._is_missing(node_config.get("fail_on_status")):
            fail_on_status_value = defaults.get("fail_on_status")
            if isinstance(fail_on_status_value, bool):
                node_config["fail_on_status"] = fail_on_status_value

        allowed_statuses_value = defaults.get("allowed_statuses")
        if MultiWorkflowRuntimeService._is_missing(node_config.get("allowed_statuses")) and isinstance(allowed_statuses_value, list):
            statuses = [int(item) for item in allowed_statuses_value if isinstance(item, int)]
            node_config["allowed_statuses"] = statuses

        headers_value = defaults.get("headers")
        if MultiWorkflowRuntimeService._is_missing(node_config.get("headers")) and isinstance(headers_value, dict):
            sanitized_headers: Dict[str, str] = {}
            for key, value in headers_value.items():
                if not isinstance(key, str) or not key.strip():
                    continue
                if value is None:
                    continue
                sanitized_headers[key] = str(value)
            node_config["headers"] = sanitized_headers

        auth_value = defaults.get("auth")
        if MultiWorkflowRuntimeService._is_missing(node_config.get("auth")) and isinstance(auth_value, dict):
            node_config["auth"] = MultiWorkflowRuntimeService._sanitize_auth_defaults(auth_value)

    @staticmethod
    def _sanitize_auth_defaults(value: Dict[str, Any]) -> Dict[str, Any]:
        forbidden_secret_fields = ("token", "password", "username")
        for field in forbidden_secret_fields:
            candidate = value.get(field)
            if isinstance(candidate, str) and candidate.strip():
                raise ValueError(
                    f"capability defaults auth.{field} must not contain inline secret values; use {field}_env"
                )
        payload: Dict[str, Any] = {}
        auth_type = value.get("type")
        if isinstance(auth_type, str) and auth_type.strip():
            payload["type"] = auth_type.strip().lower()
        for key in ("token_env", "username_env", "password_env"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                payload[key] = item.strip()
        return payload

    @staticmethod
    def _is_missing(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (list, dict, tuple, set)):
            return len(value) == 0
        return False
