from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from openai import AzureOpenAI, OpenAI

from apps.orchestrator.runtime.env import get_env

try:
    import jsonschema
except Exception:  # pragma: no cover - optional dependency
    jsonschema = None


_ROOT_DIR = Path(__file__).resolve().parents[3]
_ROUTING_SCHEMA_PATH = _ROOT_DIR / "docs" / "api" / "schemas" / "routing-decision.schema.json"


class LLMRouterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LLMUnavailableError(LLMRouterError):
    def __init__(self, message: str = "llm unavailable") -> None:
        super().__init__("ERR_LLM_UNAVAILABLE", message)


class LLMBadSchemaOutputError(LLMRouterError):
    def __init__(self, message: str = "llm output does not satisfy routing schema") -> None:
        super().__init__("ERR_LLM_BAD_SCHEMA_OUTPUT", message)


@dataclass
class RoutingDecision:
    route_type: str
    workflow_id: Optional[str]
    tags: List[str]
    confidence: float
    switch_margin: float
    reason_codes: List[str]
    clarifying_question: Optional[str]
    clarifying_options: List[str]
    model_id: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        return {
            "route_type": self.route_type,
            "workflow_id": self.workflow_id,
            "tags": list(self.tags),
            "confidence": float(self.confidence),
            "switch_margin": float(self.switch_margin),
            "reason_codes": list(self.reason_codes),
            "clarifying_question": self.clarifying_question,
            "clarifying_options": list(self.clarifying_options),
        }


def _load_routing_schema() -> Dict[str, Any]:
    if not _ROUTING_SCHEMA_PATH.exists():
        raise RuntimeError(f"routing schema file not found: {_ROUTING_SCHEMA_PATH}")
    payload = json.loads(_ROUTING_SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("routing schema must be a JSON object")
    return payload


class ResponsesLLMRouter:
    def __init__(
        self,
        model_id: Optional[str] = None,
        client: Optional[OpenAI] = None,
        force_heuristic: bool = False,
    ) -> None:
        self.model_id = model_id or get_env("ORCHESTRATOR_MODEL_ID") or get_env("OPENAI_MODEL") or "gpt-5.1-codex"
        self.force_heuristic = force_heuristic or (get_env("ORCHESTRATOR_ROUTER_MODE") or "").lower() == "heuristic"
        self.schema = _load_routing_schema()
        self.client_config_error: Optional[str] = None
        self.client = client
        if self.client is None:
            self.client = self._build_client_from_env()

    async def route(
        self,
        message_text: str,
        candidates: Sequence[Dict[str, Any]],
        active_workflow_id: Optional[str],
        confidence_threshold: float,
        switch_margin_threshold: float,
        context_summary: str,
        locale: Optional[str] = None,
        pending_disambiguation: bool = False,
    ) -> RoutingDecision:
        if self.force_heuristic:
            return self._route_heuristic(
                message_text=message_text,
                candidates=candidates,
                active_workflow_id=active_workflow_id,
                confidence_threshold=confidence_threshold,
                switch_margin_threshold=switch_margin_threshold,
            )
        if self.client is None:
            if self.client_config_error:
                raise LLMUnavailableError(self.client_config_error)
            return self._route_heuristic(
                message_text=message_text,
                candidates=candidates,
                active_workflow_id=active_workflow_id,
                confidence_threshold=confidence_threshold,
                switch_margin_threshold=switch_margin_threshold,
            )
        try:
            return await asyncio.to_thread(
                self._route_via_openai,
                message_text,
                candidates,
                active_workflow_id,
                confidence_threshold,
                switch_margin_threshold,
                context_summary,
                locale,
                pending_disambiguation,
            )
        except LLMRouterError:
            raise
        except Exception as exc:
            raise LLMUnavailableError(str(exc)) from exc

    def _build_client_from_env(self) -> Optional[OpenAI]:
        azure_endpoint = (get_env("AZURE_OPENAI_ENDPOINT") or "").strip()
        if azure_endpoint:
            azure_key = (get_env("AZURE_OPENAI_API_KEY") or get_env("OPENAI_API_KEY") or "").strip()
            azure_api_version = (get_env("AZURE_OPENAI_API_VERSION") or "").strip()
            if not azure_key:
                self.client_config_error = "AZURE_OPENAI_API_KEY is required when AZURE_OPENAI_ENDPOINT is set"
                return None
            if not azure_api_version:
                self.client_config_error = "AZURE_OPENAI_API_VERSION is required when AZURE_OPENAI_ENDPOINT is set"
                return None
            return AzureOpenAI(
                api_key=azure_key,
                azure_endpoint=azure_endpoint,
                api_version=azure_api_version,
            )
        api_key = (get_env("OPENAI_API_KEY") or "").strip()
        if not api_key:
            return None
        return OpenAI(api_key=api_key)

    def _route_via_openai(
        self,
        message_text: str,
        candidates: Sequence[Dict[str, Any]],
        active_workflow_id: Optional[str],
        confidence_threshold: float,
        switch_margin_threshold: float,
        context_summary: str,
        locale: Optional[str],
        pending_disambiguation: bool,
    ) -> RoutingDecision:
        if self.client is None:
            raise LLMUnavailableError("llm client is not configured")

        tool = {
            "type": "function",
            "name": "route_user_message",
            "description": "Decide what to do with the user's message: continue current workflow, switch, start new, ask clarification, fallback, cancel, or operator.",
            "strict": True,
            "parameters": self.schema,
        }
        instructions = (
            "You are a deterministic routing engine. "
            "You must always call route_user_message exactly once. "
            "Use only provided workflows, respect confidence and switch margin policy, "
            "and ask one concise clarifying question when uncertain."
        )
        prompt_payload = {
            "message_text": message_text,
            "active_workflow_id": active_workflow_id,
            "confidence_threshold": confidence_threshold,
            "switch_margin_threshold": switch_margin_threshold,
            "context_summary": context_summary,
            "locale": locale,
            "pending_disambiguation": pending_disambiguation,
            "candidates": list(candidates),
        }

        response = self.client.responses.create(
            model=self.model_id,
            instructions=instructions,
            input=json.dumps(prompt_payload, ensure_ascii=False),
            tools=[tool],
            tool_choice={"type": "function", "name": "route_user_message"},
            parallel_tool_calls=False,
            temperature=0,
            store=False,
        )
        payload = self._extract_tool_payload(response)
        self._validate_payload(payload)
        return RoutingDecision(
            route_type=str(payload.get("route_type")),
            workflow_id=payload.get("workflow_id"),
            tags=[str(item) for item in (payload.get("tags") or [])],
            confidence=float(payload.get("confidence") or 0),
            switch_margin=float(payload.get("switch_margin") or 0),
            reason_codes=[str(item) for item in (payload.get("reason_codes") or [])],
            clarifying_question=payload.get("clarifying_question"),
            clarifying_options=[str(item) for item in (payload.get("clarifying_options") or [])],
            model_id=getattr(response, "model", self.model_id),
        )

    def _extract_tool_payload(self, response: Any) -> Dict[str, Any]:
        output = getattr(response, "output", None)
        if not isinstance(output, list):
            raise LLMBadSchemaOutputError("responses output is missing tool call")
        for item in output:
            if getattr(item, "type", None) != "function_call":
                continue
            if getattr(item, "name", None) != "route_user_message":
                continue
            raw_args = getattr(item, "arguments", None)
            if not isinstance(raw_args, str) or not raw_args.strip():
                raise LLMBadSchemaOutputError("function call arguments are missing")
            try:
                payload = json.loads(raw_args)
            except Exception as exc:
                raise LLMBadSchemaOutputError(f"invalid function call JSON: {exc}") from exc
            if not isinstance(payload, dict):
                raise LLMBadSchemaOutputError("function call payload must be an object")
            return payload
        raise LLMBadSchemaOutputError("route_user_message function call not found")

    def _validate_payload(self, payload: Dict[str, Any]) -> None:
        if jsonschema is None:
            required = {
                "route_type",
                "workflow_id",
                "tags",
                "confidence",
                "switch_margin",
                "reason_codes",
                "clarifying_question",
                "clarifying_options",
            }
            missing = required.difference(payload.keys())
            if missing:
                raise LLMBadSchemaOutputError(f"missing required fields: {', '.join(sorted(missing))}")
            return
        try:
            jsonschema.validate(instance=payload, schema=self.schema)
        except Exception as exc:
            raise LLMBadSchemaOutputError(str(exc)) from exc

    def _route_heuristic(
        self,
        message_text: str,
        candidates: Sequence[Dict[str, Any]],
        active_workflow_id: Optional[str],
        confidence_threshold: float,
        switch_margin_threshold: float,
    ) -> RoutingDecision:
        text = (message_text or "").strip().lower()
        if any(token in text for token in ("стоп", "отмена", "отмени", "cancel", "stop")):
            return RoutingDecision(
                route_type="CANCEL",
                workflow_id=active_workflow_id,
                tags=["stop"],
                confidence=0.99,
                switch_margin=1.0,
                reason_codes=["STOP_INTENT"],
                clarifying_question=None,
                clarifying_options=[],
                model_id="heuristic",
            )
        if any(token in text for token in ("оператор", "человек", "human", "agent")):
            return RoutingDecision(
                route_type="OPERATOR",
                workflow_id=None,
                tags=["operator"],
                confidence=0.99,
                switch_margin=1.0,
                reason_codes=["OPERATOR_REQUEST"],
                clarifying_question=None,
                clarifying_options=[],
                model_id="heuristic",
            )

        scored: List[Dict[str, Any]] = []
        for candidate in candidates:
            score = float(candidate.get("score") or 0)
            for tag in candidate.get("tags") or []:
                tag_text = str(tag).strip().lower()
                if tag_text and tag_text in text:
                    score += 2.0
            for example in candidate.get("examples") or []:
                example_text = str(example).strip().lower()
                if example_text and any(part in text for part in example_text.split()[:3]):
                    score += 1.0
            name = str(candidate.get("name") or "").lower()
            if name and name in text:
                score += 1.5
            scored.append(
                {
                    "workflow_id": candidate.get("workflow_id"),
                    "tags": candidate.get("tags") or [],
                    "score": score,
                }
            )
        scored.sort(key=lambda item: float(item.get("score") or 0), reverse=True)

        if not scored:
            return RoutingDecision(
                route_type="FALLBACK",
                workflow_id=None,
                tags=[],
                confidence=0.0,
                switch_margin=0.0,
                reason_codes=["NO_CANDIDATES"],
                clarifying_question=None,
                clarifying_options=[],
                model_id="heuristic",
            )

        top = scored[0]
        second_score = float(scored[1].get("score") or 0) if len(scored) > 1 else 0.0
        top_score = float(top.get("score") or 0)
        margin = max(0.0, top_score - second_score)
        confidence = max(0.0, min(0.98, 0.35 + 0.16 * top_score))
        tags = [str(item) for item in (top.get("tags") or [])]
        workflow_id = top.get("workflow_id")

        if top_score <= 0:
            question = "Уточните, какой процесс вы хотите запустить?"
            options = [str(item.get("workflow_id")) for item in scored[:3] if item.get("workflow_id")]
            return RoutingDecision(
                route_type="DISAMBIGUATE",
                workflow_id=None,
                tags=[],
                confidence=0.2,
                switch_margin=0.0,
                reason_codes=["LOW_CONFIDENCE", "AMBIGUOUS"],
                clarifying_question=question,
                clarifying_options=options,
                model_id="heuristic",
            )

        if active_workflow_id and workflow_id == active_workflow_id and confidence >= confidence_threshold:
            return RoutingDecision(
                route_type="RESUME_CURRENT",
                workflow_id=active_workflow_id,
                tags=tags,
                confidence=confidence,
                switch_margin=margin,
                reason_codes=["STAY_IN_FLOW", "HIGH_CONFIDENCE_MATCH"],
                clarifying_question=None,
                clarifying_options=[],
                model_id="heuristic",
            )

        if active_workflow_id and workflow_id and workflow_id != active_workflow_id:
            route_type = "SWITCH_WORKFLOW" if margin >= switch_margin_threshold else "RESUME_CURRENT"
            reason_codes = ["SWITCH_MARGIN_MET", "HIGH_CONFIDENCE_MATCH"] if route_type == "SWITCH_WORKFLOW" else [
                "STAY_IN_FLOW"
            ]
            return RoutingDecision(
                route_type=route_type,
                workflow_id=workflow_id if route_type == "SWITCH_WORKFLOW" else active_workflow_id,
                tags=tags,
                confidence=confidence,
                switch_margin=margin,
                reason_codes=reason_codes,
                clarifying_question=None,
                clarifying_options=[],
                model_id="heuristic",
            )

        if confidence < confidence_threshold:
            options = [str(item.get("workflow_id")) for item in scored[:3] if item.get("workflow_id")]
            return RoutingDecision(
                route_type="DISAMBIGUATE",
                workflow_id=None,
                tags=tags,
                confidence=confidence,
                switch_margin=margin,
                reason_codes=["LOW_CONFIDENCE"],
                clarifying_question="Уточните, что именно хотите сделать?",
                clarifying_options=options,
                model_id="heuristic",
            )

        return RoutingDecision(
            route_type="START_WORKFLOW",
            workflow_id=workflow_id if isinstance(workflow_id, str) else None,
            tags=tags,
            confidence=confidence,
            switch_margin=margin,
            reason_codes=["HIGH_CONFIDENCE_MATCH"],
            clarifying_question=None,
            clarifying_options=[],
            model_id="heuristic",
        )
