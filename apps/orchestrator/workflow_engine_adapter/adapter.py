from __future__ import annotations

from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, Dict, List, Optional

from apps.orchestrator.runtime.models import Event as RuntimeEvent
from apps.orchestrator.runtime.models import Run
from apps.orchestrator.runtime.projection import project_run_payload_for_transport


@dataclass
class WorkflowEngineStateSnapshot:
    run_id: str
    workflow_id: str
    resolved_version: str
    status: str
    cancellable: bool
    commit_point_reached: Optional[bool]
    state: Dict[str, Any]
    outputs: Optional[Dict[str, Any]]


@dataclass
class WorkflowEngineResult:
    run_id: str
    events: List[Dict[str, Any]]
    state_snapshot: WorkflowEngineStateSnapshot
    cancelled: Optional[bool] = None


class WorkflowEngineAdapterError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details


class WorkflowEngineAdapter:
    def __init__(self, runtime: Any, run_store: Any) -> None:
        self.runtime = runtime
        self.run_store = run_store

    async def start(
        self,
        project_id: str,
        workflow_id: str,
        session_id: str,
        user_input: str,
        metadata: Dict[str, Any],
        tenant_id: str,
        action_type: Optional[str] = None,
        action_payload: Optional[Dict[str, Any]] = None,
    ) -> WorkflowEngineResult:
        before_event = self.runtime.store.last_event("__none__")
        run_metadata = dict(metadata or {})
        run_metadata["project_id"] = project_id
        run_metadata["session_id"] = session_id
        run_metadata.setdefault("agent_executor_mode", "live")
        run_metadata.setdefault("agent_mock", False)
        run_metadata.setdefault("llm_enabled", True)
        inputs = {
            "user_message": user_input,
            "session_id": session_id,
            "project_id": project_id,
        }
        self._merge_custom_action_inputs(
            inputs,
            action_type=action_type,
            action_payload=action_payload,
            reserved_keys={"user_message", "session_id", "project_id", "context"},
        )
        context_prefill = run_metadata.get("context_prefill")
        if isinstance(context_prefill, dict) and context_prefill:
            inputs["context"] = dict(context_prefill)
        try:
            run = await self.runtime.start_run(
                workflow_id,
                None,
                inputs,
                mode="async",
                metadata=run_metadata,
            )
        except Exception as exc:
            raise WorkflowEngineAdapterError(
                "ERR_WORKFLOW_ENGINE_UNAVAILABLE",
                str(exc),
                retryable=True,
                details=self._workflow_engine_error_details(exc),
            ) from exc

        run.metadata = dict(run.metadata or {})
        run.metadata["project_id"] = project_id
        run.metadata["session_id"] = session_id
        run.metadata["resolved_version"] = run.version_id
        run.metadata.setdefault("commit_point_reached", False)
        run.metadata.setdefault("cancellable", run.status in {"RUNNING", "WAITING_FOR_INPUT"})
        await self._save_run(run, tenant_id=tenant_id)
        events = self._collect_events(run.id, after_id=before_event.id if before_event else None)
        snapshot = self._snapshot_from_run(run)
        return WorkflowEngineResult(
            run_id=run.id,
            events=self._normalize_events(run, events),
            state_snapshot=snapshot,
        )

    async def resume(
        self,
        run_id: str,
        session_id: str,
        user_input: str,
        metadata: Dict[str, Any],
        tenant_id: str,
        action_type: Optional[str] = None,
        action_payload: Optional[Dict[str, Any]] = None,
    ) -> WorkflowEngineResult:
        run = await self.get_run(run_id, tenant_id=tenant_id)
        if run is None:
            raise WorkflowEngineAdapterError("NOT_FOUND", "run not found")
        before_event = self.runtime.store.last_event(run.id)
        run.metadata = dict(run.metadata or {})
        run.metadata.update(dict(metadata or {}))
        run.metadata["session_id"] = session_id
        run.metadata["last_user_input"] = user_input
        if action_type:
            run.metadata["last_action_type"] = action_type

        if run.status == "WAITING_FOR_INPUT":
            open_interrupts = [item for item in run.interrupts.values() if item.status == "OPEN"]
            open_interrupts.sort(key=lambda item: item.id)
            if open_interrupts:
                interrupt = open_interrupts[0]
                interrupt_input = {"text": user_input}
                self._merge_custom_action_inputs(
                    interrupt_input,
                    action_type=action_type,
                    action_payload=action_payload,
                )
                try:
                    run = await self.runtime.resume_interrupt(
                        run,
                        interrupt.id,
                        interrupt_input,
                        [],
                    )
                except Exception as exc:
                    raise WorkflowEngineAdapterError(
                        "ERR_WORKFLOW_ENGINE_UNAVAILABLE",
                        str(exc),
                        retryable=True,
                        details=self._workflow_engine_error_details(exc, run_id=run.id),
                    ) from exc
        await self._save_run(run, tenant_id=tenant_id)
        events = self._collect_events(run.id, after_id=before_event.id if before_event else None)
        snapshot = self._snapshot_from_run(run)
        return WorkflowEngineResult(
            run_id=run.id,
            events=self._normalize_events(run, events),
            state_snapshot=snapshot,
        )

    async def cancel(self, run_id: str, reason: str, tenant_id: str) -> WorkflowEngineResult:
        run = await self.get_run(run_id, tenant_id=tenant_id)
        if run is None:
            raise WorkflowEngineAdapterError("NOT_FOUND", "run not found")
        snapshot = self._snapshot_from_run(run)
        if not snapshot.cancellable:
            return WorkflowEngineResult(
                run_id=run.id,
                events=[],
                state_snapshot=snapshot,
                cancelled=False,
            )

        before_event = self.runtime.store.last_event(run.id)
        run.status = "CANCELLED"
        run.metadata = dict(run.metadata or {})
        run.metadata["cancellable"] = False
        run.metadata["cancel_reason"] = reason
        await self.runtime._publish_with_snapshot(
            run,
            [
                RuntimeEvent(
                    type="run_cancelled",
                    run_id=run.id,
                    workflow_id=run.workflow_id,
                    version_id=run.version_id,
                    payload={"reason": reason},
                    metadata=dict(run.metadata or {}),
                )
            ],
        )
        await self.runtime._notify_hooks(
            run,
            [
                RuntimeEvent(
                    type="run_cancelled",
                    run_id=run.id,
                    workflow_id=run.workflow_id,
                    version_id=run.version_id,
                    payload={"reason": reason},
                    metadata=dict(run.metadata or {}),
                )
            ],
        )
        await self._save_run(run, tenant_id=tenant_id)
        events = self._collect_events(run.id, after_id=before_event.id if before_event else None)
        return WorkflowEngineResult(
            run_id=run.id,
            events=self._normalize_events(run, events),
            state_snapshot=self._snapshot_from_run(run),
            cancelled=True,
        )

    async def get_state(self, run_id: str, tenant_id: str) -> Optional[WorkflowEngineStateSnapshot]:
        run = await self.get_run(run_id, tenant_id=tenant_id)
        if run is None:
            return None
        return self._snapshot_from_run(run)

    async def get_run(self, run_id: str, tenant_id: str) -> Optional[Run]:
        loaded = self.run_store.get(run_id, tenant_id=tenant_id)
        if isawaitable(loaded):
            return await loaded
        return loaded

    async def _save_run(self, run: Run, tenant_id: str) -> None:
        saved = self.run_store.save(run, tenant_id=tenant_id)
        if isawaitable(saved):
            await saved

    def _collect_events(self, run_id: str, after_id: Optional[str]) -> List[Any]:
        try:
            return self.runtime.store.list_events(run_id, after_id=after_id)
        except Exception:
            return []

    @staticmethod
    def _merge_custom_action_inputs(
        target: Dict[str, Any],
        action_type: Optional[str],
        action_payload: Optional[Dict[str, Any]],
        reserved_keys: Optional[set[str]] = None,
    ) -> None:
        reserved = set(reserved_keys or set())
        reserved.add("action_type")
        if isinstance(action_type, str) and action_type.strip():
            target["action_type"] = action_type.strip()
        if not isinstance(action_payload, dict):
            return
        for key, value in action_payload.items():
            normalized_key = str(key).strip()
            if not normalized_key:
                continue
            if normalized_key in reserved:
                continue
            target[normalized_key] = value

    def _snapshot_from_run(self, run: Run) -> WorkflowEngineStateSnapshot:
        metadata = dict(run.metadata or {})
        projected_state, projected_outputs = project_run_payload_for_transport(run.state, run.outputs, metadata)
        commit_point = metadata.get("commit_point_reached")
        if not isinstance(commit_point, bool):
            commit_point = False
        cancellable_raw = metadata.get("cancellable")
        if isinstance(cancellable_raw, bool):
            cancellable = cancellable_raw
        else:
            cancellable = run.status in {"RUNNING", "WAITING_FOR_INPUT"} and not bool(commit_point)
        return WorkflowEngineStateSnapshot(
            run_id=run.id,
            workflow_id=run.workflow_id,
            resolved_version=str(metadata.get("resolved_version") or run.version_id),
            status=run.status,
            cancellable=cancellable,
            commit_point_reached=bool(commit_point),
            state=dict(projected_state or {}) if isinstance(projected_state, dict) else {},
            outputs=projected_outputs if isinstance(projected_outputs, dict) else None,
        )

    def _normalize_events(self, run: Run, events: List[Any]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for event in events:
            event_type = getattr(event, "type", None)
            payload = getattr(event, "payload", None)
            if event_type == "message_generated":
                text = ""
                if isinstance(payload, dict):
                    text = str(payload.get("text") or "")
                if text:
                    normalized.append({"type": "assistant_message", "payload": {"text": text}})
            elif event_type == "run_waiting_for_input":
                schema = None
                for interrupt in run.interrupts.values():
                    if interrupt.status == "OPEN":
                        schema = interrupt.input_schema or {}
                        break
                normalized.append({"type": "request_user_input", "payload": {"schema": schema}})
            elif event_type == "run_completed":
                normalized.append(
                    {
                        "type": "completed",
                        "payload": {"result_summary": run.outputs or {}},
                    }
                )
            elif event_type in {"run_failed", "node_failed"}:
                normalized.append(
                    {
                        "type": "failed",
                        "payload": {"error_code": "RUN_FAILED", "retryable": False},
                    }
                )
            elif event_type == "run_cancelled":
                normalized.append(
                    {
                        "type": "assistant_message",
                        "payload": {"text": "Текущий workflow остановлен."},
                    }
                )
        return normalized

    @staticmethod
    def _workflow_engine_error_details(
        exc: BaseException,
        run_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        details: Dict[str, Any] = {}
        incident_code = getattr(exc, "incident_code", None)
        if isinstance(incident_code, str) and incident_code:
            details["incident_code"] = incident_code
        resolved_run_id = run_id
        if not resolved_run_id:
            candidate = getattr(exc, "run_id", None)
            if isinstance(candidate, str) and candidate:
                resolved_run_id = candidate
        if resolved_run_id:
            details["run_id"] = resolved_run_id
        attempts = getattr(exc, "attempts", None)
        if isinstance(attempts, int) and attempts > 0:
            details["attempts"] = attempts
        return details or None
