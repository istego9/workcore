from __future__ import annotations

import asyncio
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

try:
    from agents import Agent, ItemHelpers, Runner
except Exception:  # pragma: no cover - optional dependency
    Agent = None
    ItemHelpers = None
    Runner = None

try:
    import jsonschema
except Exception:  # pragma: no cover - optional dependency
    jsonschema = None

from apps.orchestrator.executors.types import EventEmitter, ExecutorResult
from apps.orchestrator.runtime.env import load_env


AGENTS_AVAILABLE = Agent is not None


@dataclass
class AgentNodeConfig:
    instructions: str
    model: Optional[str] = None
    user_input: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    output_format: Optional[str] = None
    output_schema: Optional[Dict[str, Any]] = None
    emit_partial: bool = True


class AgentExecutor:
    def __init__(self, tool_registry: Optional[Dict[str, Any]] = None) -> None:
        if not AGENTS_AVAILABLE:
            raise RuntimeError("openai-agents is not installed")
        self.tool_registry = tool_registry or {}

    def __call__(self, run, node, emit: EventEmitter) -> ExecutorResult:
        config = AgentNodeConfig(
            instructions=str(node.config.get("instructions", "")),
            model=node.config.get("model"),
            user_input=node.config.get("user_input"),
            allowed_tools=node.config.get("allowed_tools"),
            output_format=node.config.get("output_format"),
            output_schema=node.config.get("output_schema"),
            emit_partial=bool(node.config.get("emit_partial", True)),
        )
        return self.execute(run.id, node.id, config, emit)

    def execute(self, run_id: str, node_id: str, config: AgentNodeConfig, emit: EventEmitter) -> ExecutorResult:
        load_env()
        model = config.model or os.getenv("OPENAI_MODEL") or "gpt-5.2"
        agent = self._build_agent(config, model)
        trace_id = self._trace_id(run_id, node_id)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            output = asyncio.run(self._run_streamed(agent, config, emit))
        else:
            with ThreadPoolExecutor(max_workers=1) as executor:
                output = executor.submit(
                    lambda: asyncio.run(self._run_streamed(agent, config, emit))
                ).result()

        self._validate_output(config, output)
        return ExecutorResult(output=output, trace_id=trace_id)

    async def _run_streamed(
        self,
        agent: Agent,
        config: AgentNodeConfig,
        emit: EventEmitter,
    ) -> Any:
        result = Runner.run_streamed(agent, input=config.user_input or "")
        async for event in result.stream_events():
            if getattr(event, "type", None) != "run_item_stream_event":
                continue
            item = getattr(event, "item", None)
            if item is None:
                continue
            if getattr(item, "type", None) == "message_output_item" and config.emit_partial:
                text = ItemHelpers.text_message_output(item) if ItemHelpers else None
                if text:
                    emit("message_generated", {"text": text})

        return result.final_output

    def _build_agent(self, config: AgentNodeConfig, model: str) -> Agent:
        tools = self._select_tools(config.allowed_tools)
        return Agent(
            name="workflow-agent",
            instructions=config.instructions,
            model=model,
            tools=tools,
        )

    def _select_tools(self, allowed: Optional[Iterable[str]]) -> List[Any]:
        if not allowed:
            return []
        return [self.tool_registry[name] for name in allowed if name in self.tool_registry]

    @staticmethod
    def _trace_id(run_id: str, node_id: str) -> str:
        digest = hashlib.md5(f"{run_id}:{node_id}".encode()).hexdigest()
        return f"trace_{digest}"

    @staticmethod
    def _validate_output(config: AgentNodeConfig, output: Any) -> None:
        if config.output_format and config.output_format != "json":
            return
        if not config.output_schema:
            return
        if jsonschema is None:
            raise RuntimeError("jsonschema is required for output validation")
        jsonschema.validate(instance=output, schema=config.output_schema)
