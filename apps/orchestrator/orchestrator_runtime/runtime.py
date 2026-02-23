from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from apps.orchestrator.llm_adapter import LLMRouterError, ResponsesLLMRouter, RoutingDecision
from apps.orchestrator.orchestrator_runtime.store import (
    OrchestrationDecisionRecord,
    OrchestrationStore,
    OrchestratorConfigRecord,
    SessionStateRecord,
    WorkflowDefinitionRecord,
)
from apps.orchestrator.project_router import ProjectRoute, RoutingRequest
from apps.orchestrator.workflow_engine_adapter import (
    WorkflowEngineAdapter,
    WorkflowEngineAdapterError,
    WorkflowEngineResult,
)


TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"}


@dataclass
class RoutingPolicy:
    confidence_threshold: float = 0.6
    switch_margin: float = 0.2
    max_disambiguation_turns: int = 2
    top_k_candidates: int = 20
    sticky: bool = False
    allow_switch: bool = True
    explicit_switch_only: bool = False
    cooldown_seconds: int = 0
    hysteresis_margin: float = 0.0

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "RoutingPolicy":
        value = payload or {}
        confidence_threshold = _safe_float(value.get("confidence_threshold"), 0.6)
        switch_margin = _safe_float(value.get("switch_margin"), 0.2)
        max_turns = _safe_int(value.get("max_disambiguation_turns"), 2)
        top_k = _safe_int(value.get("top_k_candidates"), 20)
        sticky = _safe_bool(value.get("sticky"), False)
        allow_switch = _safe_bool(value.get("allow_switch"), True)
        explicit_switch_only = _safe_bool(value.get("explicit_switch_only"), False)
        cooldown_seconds = _safe_int(value.get("cooldown_seconds"), 0)
        hysteresis_margin = _safe_float(value.get("hysteresis_margin"), 0.0)
        return cls(
            confidence_threshold=max(0.0, min(confidence_threshold, 1.0)),
            switch_margin=max(0.0, min(switch_margin, 1.0)),
            max_disambiguation_turns=max(0, max_turns),
            top_k_candidates=max(1, min(100, top_k)),
            sticky=sticky,
            allow_switch=allow_switch,
            explicit_switch_only=explicit_switch_only,
            cooldown_seconds=max(0, cooldown_seconds),
            hysteresis_margin=max(0.0, min(hysteresis_margin, 1.0)),
        )


class OrchestratorRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ProjectOrchestratorRuntime:
    def __init__(
        self,
        store: OrchestrationStore,
        workflow_adapter: WorkflowEngineAdapter,
        llm_router: Optional[ResponsesLLMRouter] = None,
    ) -> None:
        self.store = store
        self.workflow_adapter = workflow_adapter
        self.llm_router = llm_router or ResponsesLLMRouter()

    async def handle_message(
        self,
        request: RoutingRequest,
        route: ProjectRoute,
        tenant_id: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        if route.mode == "direct":
            return await self._handle_direct(request, route, tenant_id, metadata)
        return await self._handle_orchestrated(request, route, tenant_id, metadata)

    async def evaluate_routing_replay(
        self,
        project_id: str,
        orchestrator_id: Optional[str],
        session_id: str,
        user_id: str,
        cases: Sequence[Dict[str, Any]],
        tenant_id: str,
    ) -> Dict[str, Any]:
        project = await self.store.get_project(project_id, tenant_id=tenant_id)
        if project is None:
            raise OrchestratorRuntimeError("ERR_PROJECT_NOT_FOUND", "project not found", 404)
        orchestrator = await self._resolve_orchestrator_for_eval(
            project_id=project_id,
            orchestrator_id=orchestrator_id,
            tenant_id=tenant_id,
        )
        policy = RoutingPolicy.from_dict(orchestrator.routing_policy)

        if not isinstance(cases, Sequence) or not cases:
            raise OrchestratorRuntimeError("INVALID_ARGUMENT", "cases must be a non-empty array", 400)

        replay_decisions: List[OrchestrationDecisionRecord] = []
        active_workflow_id: Optional[str] = None
        pending_disambiguation = False
        disambiguation_turns = 0
        items: List[Dict[str, Any]] = []

        total_expected_action = 0
        total_expected_workflow = 0
        total_expected_exact = 0
        matched_action = 0
        matched_workflow = 0
        matched_exact = 0
        confidence_sum = 0.0

        for index, raw_case in enumerate(cases, start=1):
            if not isinstance(raw_case, dict):
                raise OrchestratorRuntimeError(
                    "INVALID_ARGUMENT",
                    f"cases[{index - 1}] must be an object",
                    400,
                )
            case_id_raw = raw_case.get("case_id")
            case_id = (
                case_id_raw.strip()
                if isinstance(case_id_raw, str) and case_id_raw.strip()
                else f"case_{index}"
            )
            message_text_raw = raw_case.get("message_text")
            if not isinstance(message_text_raw, str) or not message_text_raw.strip():
                raise OrchestratorRuntimeError(
                    "INVALID_ARGUMENT",
                    f"cases[{index - 1}].message_text must be a non-empty string",
                    400,
                )
            message_text = message_text_raw.strip()

            metadata_raw = raw_case.get("metadata")
            if metadata_raw is None:
                metadata: Dict[str, Any] = {}
            elif isinstance(metadata_raw, dict):
                metadata = dict(metadata_raw)
            else:
                raise OrchestratorRuntimeError(
                    "INVALID_ARGUMENT",
                    f"cases[{index - 1}].metadata must be an object",
                    400,
                )

            if "active_workflow_id" in raw_case:
                active_override = raw_case.get("active_workflow_id")
                if active_override is None:
                    active_workflow_id = None
                elif isinstance(active_override, str) and active_override.strip():
                    active_workflow_id = active_override.strip()
                else:
                    raise OrchestratorRuntimeError(
                        "INVALID_ARGUMENT",
                        f"cases[{index - 1}].active_workflow_id must be a non-empty string or null",
                        400,
                    )

            expected_action = (
                raw_case.get("expected_action").strip()
                if isinstance(raw_case.get("expected_action"), str) and raw_case.get("expected_action").strip()
                else None
            )
            expected_workflow_id = (
                raw_case.get("expected_workflow_id").strip()
                if isinstance(raw_case.get("expected_workflow_id"), str) and raw_case.get("expected_workflow_id").strip()
                else None
            )

            started_at = time.monotonic()
            candidates = await self._candidate_shortlist(
                project_id=project_id,
                tenant_id=tenant_id,
                message_text=message_text,
                top_k=policy.top_k_candidates,
            )
            context_summary = self._context_summary(replay_decisions)
            try:
                decision = await self.llm_router.route(
                    message_text=message_text,
                    candidates=candidates,
                    active_workflow_id=active_workflow_id,
                    confidence_threshold=policy.confidence_threshold,
                    switch_margin_threshold=policy.switch_margin,
                    context_summary=context_summary,
                    locale=str(metadata.get("locale") or ""),
                    pending_disambiguation=pending_disambiguation,
                )
            except LLMRouterError as exc:
                raise OrchestratorRuntimeError(exc.code, exc.message, 503) from exc
            latency_ms = int((time.monotonic() - started_at) * 1000)
            confidence_sum += float(decision.confidence)

            action = decision.route_type
            chosen_workflow_id: Optional[str] = decision.workflow_id
            error_code: Optional[str] = None
            active_workflow_before = active_workflow_id

            if action == "OPERATOR":
                chosen_workflow_id = None
                pending_disambiguation = False
                disambiguation_turns = 0
            elif action == "CANCEL":
                chosen_workflow_id = active_workflow_id
                if active_workflow_id is None:
                    error_code = "ERR_NO_ACTIVE_WORKFLOW"
                else:
                    active_workflow_id = None
                pending_disambiguation = False
                disambiguation_turns = 0
            else:
                disambiguate = (
                    decision.route_type == "DISAMBIGUATE"
                    or float(decision.confidence) < policy.confidence_threshold
                )
                if disambiguate and disambiguation_turns < policy.max_disambiguation_turns:
                    action = "DISAMBIGUATE"
                    chosen_workflow_id = None
                    pending_disambiguation = True
                    disambiguation_turns += 1
                else:
                    target_workflow = await self._resolve_target_workflow(
                        project_id=project_id,
                        tenant_id=tenant_id,
                        decision=decision,
                        candidates=candidates,
                        orchestrator_fallback_workflow_id=orchestrator.fallback_workflow_id,
                    )
                    if target_workflow is None:
                        action = "FALLBACK"
                        chosen_workflow_id = None
                        error_code = "ERR_FALLBACK_NOT_AVAILABLE"
                    elif active_workflow_id and target_workflow != active_workflow_id:
                        explicit_switch_requested = self._is_explicit_switch_request(message_text)
                        switch_policy_error = self._switch_policy_error_code(
                            policy=policy,
                            recent_decisions=replay_decisions,
                            explicit_switch_requested=explicit_switch_requested,
                        )
                        required_switch_margin = min(1.0, policy.switch_margin + policy.hysteresis_margin)
                        if (
                            switch_policy_error is None
                            and decision.confidence >= policy.confidence_threshold
                            and decision.switch_margin >= required_switch_margin
                        ):
                            action = "SWITCH_WORKFLOW"
                            chosen_workflow_id = target_workflow
                            active_workflow_id = target_workflow
                        else:
                            action = "RESUME_CURRENT"
                            chosen_workflow_id = active_workflow_id
                            if switch_policy_error:
                                error_code = switch_policy_error
                    elif active_workflow_id and target_workflow == active_workflow_id:
                        action = "RESUME_CURRENT"
                        chosen_workflow_id = active_workflow_id
                    else:
                        action = "FALLBACK" if decision.route_type == "FALLBACK" else "START_WORKFLOW"
                        chosen_workflow_id = target_workflow
                        active_workflow_id = target_workflow
                    if action != "DISAMBIGUATE":
                        pending_disambiguation = False
                        disambiguation_turns = 0

            error_text = self._action_error_default_message(error_code)
            action_error = self._action_error_payload(
                error_code,
                {"text": error_text} if error_text else {},
                action,
            )
            decision_trace = self._build_decision_trace(
                mode="orchestrated",
                action=action,
                chosen_workflow_id=chosen_workflow_id,
                candidates=candidates,
                reason_codes=decision.reason_codes,
                active_workflow_id_before=active_workflow_before,
            )

            matched_action_value: Optional[bool] = None
            matched_workflow_value: Optional[bool] = None
            matched_exact_value: Optional[bool] = None
            if expected_action is not None:
                total_expected_action += 1
                matched_action_value = action == expected_action
                if matched_action_value:
                    matched_action += 1
            if expected_workflow_id is not None:
                total_expected_workflow += 1
                matched_workflow_value = chosen_workflow_id == expected_workflow_id
                if matched_workflow_value:
                    matched_workflow += 1
            if expected_action is not None and expected_workflow_id is not None:
                total_expected_exact += 1
                matched_exact_value = (
                    action == expected_action and chosen_workflow_id == expected_workflow_id
                )
                if matched_exact_value:
                    matched_exact += 1

            items.append(
                {
                    "case_id": case_id,
                    "message_text": message_text,
                    "expected_action": expected_action,
                    "expected_workflow_id": expected_workflow_id,
                    "chosen_action": action,
                    "chosen_workflow_id": chosen_workflow_id,
                    "confidence": float(decision.confidence),
                    "decision": decision.to_payload(),
                    "decision_trace": decision_trace,
                    "action_error": action_error,
                    "matched_action": matched_action_value,
                    "matched_workflow_id": matched_workflow_value,
                    "matched_exact": matched_exact_value,
                    "latency_ms": latency_ms,
                }
            )

            replay_decisions.insert(
                0,
                OrchestrationDecisionRecord(
                    decision_id=f"eval_{case_id}",
                    tenant_id=tenant_id,
                    project_id=project_id,
                    orchestrator_id=orchestrator.orchestrator_id,
                    session_id=session_id,
                    message_id=f"eval_msg_{index}",
                    mode="orchestrated_eval",
                    active_run_id=None,
                    context_ref={"eval": True},
                    candidates=[
                        {
                            "workflow_id": item.get("workflow_id"),
                            "score": item.get("score"),
                            "reason_codes": item.get("reason_codes", []),
                        }
                        for item in candidates
                    ],
                    chosen_action=action,
                    chosen_workflow_id=chosen_workflow_id,
                    confidence=float(decision.confidence),
                    latency_ms=latency_ms,
                    model_id=decision.model_id,
                    error_code=error_code,
                    created_at=_now(),
                ),
            )
            replay_decisions = replay_decisions[:20]

        return {
            "mode": "offline_eval",
            "project_id": project_id,
            "orchestrator_id": orchestrator.orchestrator_id,
            "session_id": session_id,
            "user_id": user_id,
            "total_cases": len(items),
            "metrics": {
                "cases_with_expected_action": total_expected_action,
                "cases_with_expected_workflow": total_expected_workflow,
                "cases_with_exact_expectations": total_expected_exact,
                "matched_action": matched_action,
                "matched_workflow_id": matched_workflow,
                "matched_exact": matched_exact,
                "action_accuracy": _ratio(matched_action, total_expected_action),
                "workflow_accuracy": _ratio(matched_workflow, total_expected_workflow),
                "exact_match_rate": _ratio(matched_exact, total_expected_exact),
                "average_confidence": round(confidence_sum / len(items), 6) if items else 0.0,
            },
            "items": items,
        }

    async def _handle_direct(
        self,
        request: RoutingRequest,
        route: ProjectRoute,
        tenant_id: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        workflow = route.workflow_definition
        if workflow is None:
            raise OrchestratorRuntimeError("ERR_WORKFLOW_NOT_IN_PROJECT", "workflow is not configured", 409)

        state = await self.store.get_session_state(request.project_id, request.session_id, tenant_id=tenant_id)
        if state is None:
            state = SessionStateRecord(
                tenant_id=tenant_id,
                project_id=request.project_id,
                session_id=request.session_id,
                orchestrator_id=None,
                active_run_id=None,
                pending_disambiguation=False,
                pending_question=None,
                pending_options=[],
                disambiguation_turns=0,
                last_user_message_id=None,
                created_at=_now(),
                updated_at=_now(),
            )

        action = "START_WORKFLOW"
        run_result: Optional[WorkflowEngineResult] = None
        from_run_id = state.active_run_id
        active_workflow_id_before: Optional[str] = None
        metadata_with_context = await self._metadata_with_session_context(
            metadata=metadata,
            project_id=request.project_id,
            session_id=request.session_id,
            tenant_id=tenant_id,
        )
        if state.active_run_id:
            active = await self.workflow_adapter.get_state(state.active_run_id, tenant_id=tenant_id)
            if active:
                active_workflow_id_before = active.workflow_id
            if active and active.workflow_id == workflow.workflow_id and active.status == "WAITING_FOR_INPUT":
                action = "RESUME_CURRENT"
                run_result = await self.workflow_adapter.resume(
                    state.active_run_id,
                    request.session_id,
                    request.message_text,
                    metadata_with_context,
                    tenant_id=tenant_id,
                    action_type=request.action_type,
                    action_payload=request.action_payload,
                )

        if run_result is None:
            run_result = await self.workflow_adapter.start(
                request.project_id,
                workflow.workflow_id,
                request.session_id,
                request.message_text,
                metadata_with_context,
                tenant_id=tenant_id,
                action_type=request.action_type,
                action_payload=request.action_payload,
            )
            await self.store.append_stack_entry(
                request.project_id,
                request.session_id,
                tenant_id=tenant_id,
                run_id=run_result.run_id,
                transition_reason="direct_start",
                from_run_id=from_run_id,
            )

        state.active_run_id = None if run_result.state_snapshot.status in TERMINAL_STATUSES else run_result.run_id
        state.pending_disambiguation = False
        state.pending_question = None
        state.pending_options = []
        state.disambiguation_turns = 0
        state.last_user_message_id = request.message_id
        state = await self.store.save_session_state(state)

        decision = RoutingDecision(
            route_type=action,
            workflow_id=workflow.workflow_id,
            tags=list(workflow.tags or []),
            confidence=1.0,
            switch_margin=1.0,
            reason_codes=["HIGH_CONFIDENCE_MATCH"],
            clarifying_question=None,
            clarifying_options=[],
            model_id="direct",
        )
        direct_candidates = [
            {
                "workflow_id": workflow.workflow_id,
                "score": 1.0,
                "reason_codes": ["DIRECT_HINT"],
            }
        ]
        decision_id = _new_id("dec")
        await self.store.save_decision(
            OrchestrationDecisionRecord(
                decision_id=decision_id,
                tenant_id=tenant_id,
                project_id=request.project_id,
                orchestrator_id=None,
                session_id=request.session_id,
                message_id=request.message_id,
                mode="direct",
                active_run_id=from_run_id,
                context_ref={"source": "direct_workflow_mode"},
                candidates=direct_candidates,
                chosen_action=action,
                chosen_workflow_id=workflow.workflow_id,
                confidence=1.0,
                latency_ms=0,
                model_id="direct",
                error_code=None,
            )
        )

        stack = await self._stack_view(request.project_id, request.session_id, tenant_id=tenant_id)
        return {
            "decision_id": decision_id,
            "mode": "direct",
            "orchestrator_id": None,
            "chosen_action": action,
            "chosen_workflow_id": workflow.workflow_id,
            "run_id": run_result.run_id,
            "active_run_id": state.active_run_id,
            "confidence": decision.confidence,
            "decision": decision.to_payload(),
            "decision_trace": self._build_decision_trace(
                mode="direct",
                action=action,
                chosen_workflow_id=workflow.workflow_id,
                candidates=direct_candidates,
                reason_codes=decision.reason_codes,
                active_workflow_id_before=active_workflow_id_before,
            ),
            "message": self._response_message_from_events(run_result.events),
            "events": run_result.events,
            "stack": stack,
        }

    async def _handle_orchestrated(
        self,
        request: RoutingRequest,
        route: ProjectRoute,
        tenant_id: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        orchestrator = route.orchestrator
        if orchestrator is None:
            raise OrchestratorRuntimeError("ERR_ORCHESTRATOR_NOT_IN_PROJECT", "orchestrator is required", 409)
        policy = RoutingPolicy.from_dict(orchestrator.routing_policy)
        if route.project.settings.get("orchestrator_enabled") is False:
            raise OrchestratorRuntimeError("PRECONDITION_FAILED", "orchestrator is disabled for project", 409)

        state = await self.store.get_session_state(request.project_id, request.session_id, tenant_id=tenant_id)
        if state is None:
            state = SessionStateRecord(
                tenant_id=tenant_id,
                project_id=request.project_id,
                session_id=request.session_id,
                orchestrator_id=orchestrator.orchestrator_id,
                active_run_id=None,
                pending_disambiguation=False,
                pending_question=None,
                pending_options=[],
                disambiguation_turns=0,
                last_user_message_id=None,
                created_at=_now(),
                updated_at=_now(),
            )
        active_run_before = state.active_run_id
        active_state = None
        if state.active_run_id:
            active_state = await self.workflow_adapter.get_state(state.active_run_id, tenant_id=tenant_id)
            if active_state is None:
                state.active_run_id = None

        candidates = await self._candidate_shortlist(
            project_id=request.project_id,
            tenant_id=tenant_id,
            message_text=request.message_text,
            top_k=policy.top_k_candidates,
        )
        metadata_with_context = await self._metadata_with_session_context(
            metadata=metadata,
            project_id=request.project_id,
            session_id=request.session_id,
            tenant_id=tenant_id,
        )
        recent_decisions = await self.store.list_recent_decisions(
            request.project_id,
            request.session_id,
            tenant_id=tenant_id,
            limit=5,
        )
        context_summary = self._context_summary(recent_decisions)

        started_at = time.monotonic()
        if candidates:
            try:
                decision = await self.llm_router.route(
                    message_text=request.message_text,
                    candidates=candidates,
                    active_workflow_id=active_state.workflow_id if active_state else None,
                    confidence_threshold=policy.confidence_threshold,
                    switch_margin_threshold=policy.switch_margin,
                    context_summary=context_summary,
                    locale=str(request.metadata.get("locale") or ""),
                    pending_disambiguation=state.pending_disambiguation,
                )
            except LLMRouterError as exc:
                raise OrchestratorRuntimeError(exc.code, exc.message, 503) from exc
        else:
            decision = RoutingDecision(
                route_type="FALLBACK",
                workflow_id=None,
                tags=[],
                confidence=0.0,
                switch_margin=0.0,
                reason_codes=["NO_CANDIDATES"],
                clarifying_question=None,
                clarifying_options=[],
                model_id="fallback",
            )
        latency_ms = int((time.monotonic() - started_at) * 1000)

        action = decision.route_type
        chosen_workflow_id: Optional[str] = decision.workflow_id
        run_id: Optional[str] = None
        events: List[Dict[str, Any]] = []
        error_code: Optional[str] = None
        message_payload = {"type": "assistant_message", "text": "Готово.", "options": []}
        from_run_id = active_state.run_id if active_state else None

        if action == "OPERATOR":
            message_payload = {
                "type": "assistant_message",
                "text": "Передаю запрос оператору. Опишите, пожалуйста, задачу подробнее.",
                "options": [],
            }
            chosen_workflow_id = None
        elif action == "CANCEL":
            if active_state is None:
                error_code = "ERR_NO_ACTIVE_WORKFLOW"
                message_payload = {
                    "type": "assistant_message",
                    "text": "Сейчас нет активного workflow для отмены.",
                    "options": [],
                }
            elif not active_state.cancellable:
                error_code = "ERR_CANCEL_NOT_ALLOWED"
                message_payload = {
                    "type": "assistant_message",
                    "text": "Нельзя отменить workflow на текущем шаге.",
                    "options": [],
                }
            else:
                cancel_result = await self.workflow_adapter.cancel(active_state.run_id, "user_cancel", tenant_id=tenant_id)
                action = "CANCEL"
                run_id = cancel_result.run_id
                events = cancel_result.events
                message_payload = self._response_message_from_events(events)
                state.active_run_id = None
        else:
            disambiguate = (
                decision.route_type == "DISAMBIGUATE"
                or float(decision.confidence) < policy.confidence_threshold
            )
            if disambiguate and state.disambiguation_turns < policy.max_disambiguation_turns:
                action = "DISAMBIGUATE"
                question = decision.clarifying_question or "Уточните, пожалуйста, какой процесс вам нужен?"
                options = list(decision.clarifying_options or [])[:3]
                state.pending_disambiguation = True
                state.pending_question = question
                state.pending_options = options
                state.disambiguation_turns += 1
                state.last_user_message_id = request.message_id
                await self.store.save_session_state(state)
                message_payload = {"type": "clarification", "text": question, "options": options}
                chosen_workflow_id = None
            else:
                target_workflow = await self._resolve_target_workflow(
                    project_id=request.project_id,
                    tenant_id=tenant_id,
                    decision=decision,
                    candidates=candidates,
                    orchestrator_fallback_workflow_id=orchestrator.fallback_workflow_id,
                )
                if target_workflow is None:
                    action = "FALLBACK"
                    error_code = "ERR_FALLBACK_NOT_AVAILABLE"
                    chosen_workflow_id = None
                    message_payload = {
                        "type": "assistant_message",
                        "text": "Не удалось определить подходящий workflow. Опишите задачу подробнее.",
                        "options": [],
                    }
                elif active_state and target_workflow != active_state.workflow_id:
                    explicit_switch_requested = self._is_explicit_switch_request(request.message_text)
                    switch_policy_error = self._switch_policy_error_code(
                        policy=policy,
                        recent_decisions=recent_decisions,
                        explicit_switch_requested=explicit_switch_requested,
                    )
                    required_switch_margin = min(1.0, policy.switch_margin + policy.hysteresis_margin)
                    if (
                        switch_policy_error is None
                        and decision.confidence >= policy.confidence_threshold
                        and decision.switch_margin >= required_switch_margin
                    ):
                        if not active_state.cancellable:
                            action = "RESUME_CURRENT"
                            error_code = "ERR_CANCEL_NOT_ALLOWED"
                            chosen_workflow_id = active_state.workflow_id
                            message_payload = {
                                "type": "assistant_message",
                                "text": "Сейчас нельзя переключить workflow: текущий шаг не допускает отмену.",
                                "options": [],
                            }
                        else:
                            cancelled = await self.workflow_adapter.cancel(
                                active_state.run_id,
                                "switch_workflow",
                                tenant_id=tenant_id,
                            )
                            started = await self.workflow_adapter.start(
                                request.project_id,
                                target_workflow,
                                request.session_id,
                                request.message_text,
                                metadata_with_context,
                                tenant_id=tenant_id,
                                action_type=request.action_type,
                                action_payload=request.action_payload,
                            )
                            action = "SWITCH_WORKFLOW"
                            chosen_workflow_id = target_workflow
                            run_id = started.run_id
                            events = list(cancelled.events) + list(started.events)
                            message_payload = self._response_message_from_events(events)
                            await self.store.append_stack_entry(
                                request.project_id,
                                request.session_id,
                                tenant_id=tenant_id,
                                run_id=started.run_id,
                                transition_reason="switch_workflow",
                                from_run_id=active_state.run_id,
                            )
                            state.active_run_id = (
                                None if started.state_snapshot.status in TERMINAL_STATUSES else started.run_id
                            )
                    else:
                        action = "RESUME_CURRENT"
                        if switch_policy_error:
                            error_code = switch_policy_error
                        resumed = await self.workflow_adapter.resume(
                            active_state.run_id,
                            request.session_id,
                            request.message_text,
                            metadata_with_context,
                            tenant_id=tenant_id,
                            action_type=request.action_type,
                            action_payload=request.action_payload,
                        )
                        run_id = resumed.run_id
                        events = resumed.events
                        chosen_workflow_id = active_state.workflow_id
                        if switch_policy_error:
                            message_payload = self._switch_policy_message(switch_policy_error)
                        else:
                            message_payload = self._response_message_from_events(events)
                        state.active_run_id = None if resumed.state_snapshot.status in TERMINAL_STATUSES else resumed.run_id
                elif active_state and target_workflow == active_state.workflow_id:
                    action = "RESUME_CURRENT"
                    resumed = await self.workflow_adapter.resume(
                        active_state.run_id,
                        request.session_id,
                        request.message_text,
                        metadata_with_context,
                        tenant_id=tenant_id,
                        action_type=request.action_type,
                        action_payload=request.action_payload,
                    )
                    run_id = resumed.run_id
                    events = resumed.events
                    chosen_workflow_id = active_state.workflow_id
                    message_payload = self._response_message_from_events(events)
                    state.active_run_id = None if resumed.state_snapshot.status in TERMINAL_STATUSES else resumed.run_id
                else:
                    started = await self.workflow_adapter.start(
                        request.project_id,
                        target_workflow,
                        request.session_id,
                        request.message_text,
                        metadata_with_context,
                        tenant_id=tenant_id,
                        action_type=request.action_type,
                        action_payload=request.action_payload,
                    )
                    action = "FALLBACK" if decision.route_type == "FALLBACK" else "START_WORKFLOW"
                    chosen_workflow_id = target_workflow
                    run_id = started.run_id
                    events = started.events
                    message_payload = self._response_message_from_events(events)
                    await self.store.append_stack_entry(
                        request.project_id,
                        request.session_id,
                        tenant_id=tenant_id,
                        run_id=started.run_id,
                        transition_reason="fallback_start" if action == "FALLBACK" else "orchestrator_start",
                        from_run_id=from_run_id,
                    )
                    state.active_run_id = None if started.state_snapshot.status in TERMINAL_STATUSES else started.run_id
                if action != "DISAMBIGUATE":
                    state.pending_disambiguation = False
                    state.pending_question = None
                    state.pending_options = []
                    state.disambiguation_turns = 0

        state.orchestrator_id = orchestrator.orchestrator_id
        state.last_user_message_id = request.message_id
        if action not in {"CANCEL", "DISAMBIGUATE"} and run_id is None and active_state:
            state.active_run_id = active_state.run_id
        state = await self.store.save_session_state(state)

        decision_id = _new_id("dec")
        decision_record = OrchestrationDecisionRecord(
            decision_id=decision_id,
            tenant_id=tenant_id,
            project_id=request.project_id,
            orchestrator_id=orchestrator.orchestrator_id,
            session_id=request.session_id,
            message_id=request.message_id,
            mode="orchestrated",
            active_run_id=active_run_before,
            context_ref={
                "recent_decisions": [item.decision_id for item in recent_decisions],
                "candidate_count": len(candidates),
                "pending_disambiguation": bool(state.pending_disambiguation),
                "context_prefill_keys": len(
                    metadata_with_context.get("context_prefill", {})
                    if isinstance(metadata_with_context.get("context_prefill"), dict)
                    else {}
                ),
            },
            candidates=[
                {
                    "workflow_id": item.get("workflow_id"),
                    "score": item.get("score"),
                    "reason_codes": item.get("reason_codes", []),
                }
                for item in candidates
            ],
            chosen_action=action,
            chosen_workflow_id=chosen_workflow_id,
            confidence=float(decision.confidence),
            latency_ms=latency_ms,
            model_id=decision.model_id,
            error_code=error_code,
        )
        await self.store.save_decision(decision_record)

        stack = await self._stack_view(request.project_id, request.session_id, tenant_id=tenant_id)
        action_error = self._action_error_payload(error_code, message_payload, action)
        return {
            "decision_id": decision_id,
            "mode": "orchestrated",
            "orchestrator_id": orchestrator.orchestrator_id,
            "chosen_action": action,
            "chosen_workflow_id": chosen_workflow_id,
            "run_id": run_id,
            "active_run_id": state.active_run_id,
            "confidence": float(decision.confidence),
            "decision": decision.to_payload(),
            "decision_trace": self._build_decision_trace(
                mode="orchestrated",
                action=action,
                chosen_workflow_id=chosen_workflow_id,
                candidates=candidates,
                reason_codes=decision.reason_codes,
                active_workflow_id_before=active_state.workflow_id if active_state else None,
            ),
            "action_error": action_error,
            "message": message_payload,
            "events": events,
            "stack": stack,
        }

    async def get_stack(
        self,
        project_id: str,
        session_id: str,
        tenant_id: str,
    ) -> Dict[str, Any]:
        project = await self.store.get_project(project_id, tenant_id=tenant_id)
        if project is None:
            raise OrchestratorRuntimeError("ERR_PROJECT_NOT_FOUND", "project not found", 404)
        return {
            "project_id": project_id,
            "session_id": session_id,
            "items": await self._stack_view(project_id, session_id, tenant_id=tenant_id),
        }

    async def _resolve_orchestrator_for_eval(
        self,
        project_id: str,
        orchestrator_id: Optional[str],
        tenant_id: str,
    ) -> OrchestratorConfigRecord:
        target_id = orchestrator_id
        if not target_id:
            project = await self.store.get_project(project_id, tenant_id=tenant_id)
            if project and project.default_orchestrator_id:
                target_id = project.default_orchestrator_id
        if not target_id:
            configs = await self.store.list_orchestrator_configs(project_id, tenant_id=tenant_id)
            if configs:
                target_id = configs[0].orchestrator_id
        if not target_id:
            raise OrchestratorRuntimeError(
                "ERR_ORCHESTRATOR_NOT_IN_PROJECT",
                "orchestrator is not configured for project",
                409,
            )
        config = await self.store.get_orchestrator_config(project_id, target_id, tenant_id=tenant_id)
        if config is None:
            raise OrchestratorRuntimeError(
                "ERR_ORCHESTRATOR_NOT_IN_PROJECT",
                "orchestrator does not belong to project",
                409,
            )
        return config

    async def _resolve_target_workflow(
        self,
        project_id: str,
        tenant_id: str,
        decision: RoutingDecision,
        candidates: Sequence[Dict[str, Any]],
        orchestrator_fallback_workflow_id: Optional[str],
    ) -> Optional[str]:
        if decision.workflow_id:
            workflow = await self.store.get_workflow_definition(
                project_id,
                decision.workflow_id,
                tenant_id=tenant_id,
            )
            if workflow and workflow.active:
                return workflow.workflow_id
        if decision.route_type == "FALLBACK":
            if orchestrator_fallback_workflow_id:
                fallback = await self.store.get_workflow_definition(
                    project_id,
                    orchestrator_fallback_workflow_id,
                    tenant_id=tenant_id,
                )
                if fallback and fallback.active:
                    return fallback.workflow_id
            fallback = await self.store.get_fallback_workflow_definition(project_id, tenant_id=tenant_id)
            return fallback.workflow_id if fallback else None
        if candidates:
            return str(candidates[0].get("workflow_id"))
        if orchestrator_fallback_workflow_id:
            fallback = await self.store.get_workflow_definition(
                project_id,
                orchestrator_fallback_workflow_id,
                tenant_id=tenant_id,
            )
            if fallback and fallback.active:
                return fallback.workflow_id
        fallback = await self.store.get_fallback_workflow_definition(project_id, tenant_id=tenant_id)
        return fallback.workflow_id if fallback else None

    async def _candidate_shortlist(
        self,
        project_id: str,
        tenant_id: str,
        message_text: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        definitions = await self.store.list_workflow_definitions(project_id, tenant_id=tenant_id, active_only=True)
        text = (message_text or "").strip().lower()
        items: List[Dict[str, Any]] = []
        for definition in definitions:
            score = 0.0
            reason_codes: List[str] = []
            for tag in definition.tags:
                normalized = str(tag).strip().lower()
                if normalized and normalized in text:
                    score += 2.0
                    reason_codes.append("HIGH_CONFIDENCE_MATCH")
            for example in definition.examples:
                example_text = str(example).strip().lower()
                if not example_text:
                    continue
                if any(token for token in example_text.split() if token in text):
                    score += 1.0
                    reason_codes.append("HIGH_CONFIDENCE_MATCH")
            if definition.name.lower() in text:
                score += 1.2
                reason_codes.append("HIGH_CONFIDENCE_MATCH")
            items.append(
                {
                    "workflow_id": definition.workflow_id,
                    "name": definition.name,
                    "description": definition.description,
                    "tags": list(definition.tags or []),
                    "examples": list(definition.examples or []),
                    "score": round(score, 4),
                    "reason_codes": sorted(set(reason_codes)),
                }
            )
        items.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
        if top_k > 0:
            return items[:top_k]
        return items

    def _switch_policy_error_code(
        self,
        policy: RoutingPolicy,
        recent_decisions: Sequence[OrchestrationDecisionRecord],
        explicit_switch_requested: bool,
    ) -> Optional[str]:
        if not policy.allow_switch:
            return "ERR_SWITCH_DISABLED"
        if policy.cooldown_seconds > 0:
            now = _now()
            for decision in recent_decisions:
                if decision.chosen_action != "SWITCH_WORKFLOW":
                    continue
                elapsed_seconds = (now - decision.created_at).total_seconds()
                if elapsed_seconds < policy.cooldown_seconds:
                    return "ERR_SWITCH_COOLDOWN_ACTIVE"
                break
        if policy.explicit_switch_only and not explicit_switch_requested:
            return "ERR_SWITCH_EXPLICIT_REQUIRED"
        if policy.sticky and not explicit_switch_requested:
            return "ERR_STICKY_POLICY_ACTIVE"
        return None

    @staticmethod
    def _is_explicit_switch_request(message_text: str) -> bool:
        text = (message_text or "").strip().lower()
        if not text:
            return False
        tokens = (
            "переключ",
            "смени",
            "смени ",
            "другой процесс",
            "другой workflow",
            "switch",
            "change workflow",
            "use another flow",
        )
        return any(token in text for token in tokens)

    @staticmethod
    def _switch_policy_message(error_code: str) -> Dict[str, Any]:
        if error_code == "ERR_SWITCH_DISABLED":
            text = "Переключение workflow отключено политикой маршрутизации."
        elif error_code == "ERR_SWITCH_COOLDOWN_ACTIVE":
            text = "Переключение временно недоступно: действует cooldown после предыдущего переключения."
        elif error_code == "ERR_SWITCH_EXPLICIT_REQUIRED":
            text = "Для переключения workflow укажите явную команду на смену сценария."
        elif error_code == "ERR_STICKY_POLICY_ACTIVE":
            text = "Сохраняем текущий workflow по sticky-политике."
        else:
            text = "Переключение workflow недоступно из-за политики маршрутизации."
        return {"type": "assistant_message", "text": text, "options": []}

    def _context_summary(self, decisions: Sequence[OrchestrationDecisionRecord]) -> str:
        if not decisions:
            return ""
        parts: List[str] = []
        for item in decisions[:5]:
            parts.append(f"{item.message_id}:{item.chosen_action}:{item.chosen_workflow_id or '-'}")
        return " | ".join(parts)

    async def _metadata_with_session_context(
        self,
        metadata: Dict[str, Any],
        project_id: str,
        session_id: str,
        tenant_id: str,
    ) -> Dict[str, Any]:
        payload = dict(metadata or {})
        context_prefill = await self.store.get_context_values(
            "session",
            session_id,
            tenant_id=tenant_id,
            project_id=project_id,
            keys=None,
        )
        if context_prefill:
            payload["context_prefill"] = context_prefill
        return payload

    async def _stack_view(self, project_id: str, session_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        entries = await self.store.list_stack(project_id, session_id, tenant_id=tenant_id)
        items: List[Dict[str, Any]] = []
        for entry in entries:
            run = await self.workflow_adapter.get_run(entry.run_id, tenant_id=tenant_id)
            items.append(
                {
                    "run_id": entry.run_id,
                    "workflow_id": run.workflow_id if run else "",
                    "status": run.status if run else "UNKNOWN",
                    "transition_reason": entry.transition_reason,
                    "created_at": entry.created_at.isoformat(),
                }
            )
        return items

    def _response_message_from_events(self, events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        for event in events:
            if event.get("type") == "assistant_message":
                text = str((event.get("payload") or {}).get("text") or "").strip()
                if text:
                    return {"type": "assistant_message", "text": text, "options": []}
        for event in events:
            if event.get("type") == "request_user_input":
                return {
                    "type": "assistant_message",
                    "text": "Нужны дополнительные данные для продолжения workflow.",
                    "options": [],
                }
        for event in events:
            if event.get("type") == "completed":
                return {"type": "assistant_message", "text": "Workflow завершен.", "options": []}
        for event in events:
            if event.get("type") == "failed":
                return {"type": "assistant_message", "text": "Workflow завершился с ошибкой.", "options": []}
        return {"type": "assistant_message", "text": "Запрос обработан.", "options": []}

    def _build_decision_trace(
        self,
        mode: str,
        action: str,
        chosen_workflow_id: Optional[str],
        candidates: Sequence[Dict[str, Any]],
        reason_codes: Sequence[Any],
        active_workflow_id_before: Optional[str],
    ) -> Dict[str, Any]:
        normalized_candidates: List[Dict[str, Any]] = []
        for candidate in candidates:
            workflow_id_raw = candidate.get("workflow_id")
            if not isinstance(workflow_id_raw, str) or not workflow_id_raw.strip():
                continue
            score_value: Optional[float] = None
            score_raw = candidate.get("score")
            if score_raw is not None:
                try:
                    score_value = float(score_raw)
                except (TypeError, ValueError):
                    score_value = None
            raw_reason_codes = candidate.get("reason_codes")
            normalized_reason_codes: List[str] = []
            if isinstance(raw_reason_codes, list):
                normalized_reason_codes = [
                    str(item).strip()
                    for item in raw_reason_codes
                    if isinstance(item, str) and item.strip()
                ]
            normalized_candidates.append(
                {
                    "workflow_id": workflow_id_raw.strip(),
                    "score": score_value,
                    "reason_codes": normalized_reason_codes,
                }
            )

        normalized_reason_codes = [
            str(item).strip()
            for item in reason_codes
            if isinstance(item, str) and item.strip()
        ]
        selection_reason = normalized_reason_codes[0] if normalized_reason_codes else action

        switch_from_workflow_id: Optional[str] = None
        switch_to_workflow_id: Optional[str] = None
        switch_reason: Optional[str] = None
        if action == "SWITCH_WORKFLOW":
            switch_from_workflow_id = active_workflow_id_before
            switch_to_workflow_id = chosen_workflow_id
            switch_reason = selection_reason

        return {
            "mode": mode,
            "candidates": normalized_candidates,
            "selected_action": action,
            "selected_workflow_id": chosen_workflow_id,
            "reason_codes": normalized_reason_codes,
            "selection_reason": selection_reason,
            "switch_from_workflow_id": switch_from_workflow_id,
            "switch_to_workflow_id": switch_to_workflow_id,
            "switch_reason": switch_reason,
        }

    @staticmethod
    def _action_error_default_message(error_code: Optional[str]) -> Optional[str]:
        if error_code == "ERR_NO_ACTIVE_WORKFLOW":
            return "Сейчас нет активного workflow для отмены."
        if error_code == "ERR_FALLBACK_NOT_AVAILABLE":
            return "Не удалось определить подходящий workflow. Опишите задачу подробнее."
        if error_code in {
            "ERR_SWITCH_DISABLED",
            "ERR_SWITCH_COOLDOWN_ACTIVE",
            "ERR_SWITCH_EXPLICIT_REQUIRED",
            "ERR_STICKY_POLICY_ACTIVE",
        }:
            return str(ProjectOrchestratorRuntime._switch_policy_message(error_code).get("text") or "")
        if error_code == "ERR_CANCEL_NOT_ALLOWED":
            return "Нельзя отменить workflow на текущем шаге."
        return None

    @staticmethod
    def _action_error_payload(
        error_code: Optional[str],
        message_payload: Dict[str, Any],
        action: str,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(error_code, str) or not error_code.strip():
            return None
        message = str(message_payload.get("text") or "").strip() or "Routing action error."
        code = error_code.strip()
        category = "route" if code in {"ERR_FALLBACK_NOT_AVAILABLE"} else "action"
        retryable = code in {
            "ERR_NO_ACTIVE_WORKFLOW",
            "ERR_FALLBACK_NOT_AVAILABLE",
            "ERR_SWITCH_COOLDOWN_ACTIVE",
            "ERR_SWITCH_EXPLICIT_REQUIRED",
            "ERR_STICKY_POLICY_ACTIVE",
        }
        return {
            "code": code,
            "message": message,
            "retryable": retryable,
            "category": category,
            "action": action,
        }


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
    return default


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 6)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _now() -> Any:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
