from __future__ import annotations

import asyncio
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Dict, Iterable, List, Optional

try:
    from agents import (
        Agent,
        AgentOutputSchemaBase,
        ItemHelpers,
        ModelBehaviorError,
        OpenAIProvider,
        RunConfig,
        Runner,
    )
except Exception:  # pragma: no cover - optional dependency
    Agent = None
    AgentOutputSchemaBase = None
    ItemHelpers = None
    ModelBehaviorError = RuntimeError
    OpenAIProvider = None
    RunConfig = None
    Runner = None

try:
    import jsonschema
except Exception:  # pragma: no cover - optional dependency
    jsonschema = None

try:
    from openai import AsyncAzureOpenAI
except Exception:  # pragma: no cover - optional dependency
    AsyncAzureOpenAI = None

from apps.orchestrator.executors.types import EventEmitter, ExecutorResult
from apps.orchestrator.runtime.env import load_env


AGENTS_AVAILABLE = Agent is not None
_MISSING = object()


class _RawJSONSchemaOutput(AgentOutputSchemaBase if AgentOutputSchemaBase is not None else object):
    """Pass-through JSON schema for Agent output_type when schema is user-defined."""

    def __init__(self, schema: Dict[str, Any], strict_json_schema: bool = False) -> None:
        self._schema = schema
        self._strict_json_schema = strict_json_schema

    def is_plain_text(self) -> bool:
        return False

    def name(self) -> str:
        return "workflow_output"

    def json_schema(self) -> Dict[str, Any]:
        return self._schema

    def is_strict_json_schema(self) -> bool:
        return self._strict_json_schema

    def validate_json(self, json_str: str) -> Any:
        try:
            value = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ModelBehaviorError(f"Invalid JSON output: {exc}") from exc
        if jsonschema is None:
            return value
        try:
            jsonschema.validate(instance=value, schema=self._schema)
        except Exception as exc:
            raise ModelBehaviorError(str(exc)) from exc
        return value


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
            user_input=self._resolve_user_input(run, node),
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
        run_config = self._build_run_config()
        trace_id = self._trace_id(run_id, node_id)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            streamed_result = asyncio.run(self._run_streamed(agent, config, emit, run_config))
        else:
            with ThreadPoolExecutor(max_workers=1) as executor:
                streamed_result = executor.submit(
                    lambda: asyncio.run(self._run_streamed(agent, config, emit, run_config))
                ).result()

        output, usage = self._split_stream_output(streamed_result)
        output = self._normalize_output(config, output)
        self._validate_output(config, output)
        return ExecutorResult(output=output, trace_id=trace_id, usage=usage)

    async def _run_streamed(
        self,
        agent: Agent,
        config: AgentNodeConfig,
        emit: EventEmitter,
        run_config: Optional[RunConfig],
    ) -> Any:
        result = Runner.run_streamed(agent, input=config.user_input or "", run_config=run_config)
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

        return result

    @classmethod
    def _split_stream_output(cls, streamed_result: Any) -> tuple[Any, Optional[Dict[str, Any]]]:
        output = getattr(streamed_result, "final_output", streamed_result)
        context_wrapper = getattr(streamed_result, "context_wrapper", None)
        usage = cls._usage_to_dict(getattr(context_wrapper, "usage", None))
        return output, usage

    @classmethod
    def _usage_to_dict(cls, usage: Any) -> Optional[Dict[str, Any]]:
        if usage is None:
            return None
        normalized = cls._to_jsonable(usage)
        if not isinstance(normalized, dict):
            return None
        return normalized

    @classmethod
    def _to_jsonable(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): cls._to_jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._to_jsonable(item) for item in value]
        if hasattr(value, "model_dump"):
            try:
                return cls._to_jsonable(value.model_dump(mode="json"))
            except TypeError:
                return cls._to_jsonable(value.model_dump())
        if is_dataclass(value):
            return cls._to_jsonable(asdict(value))
        if hasattr(value, "to_dict"):
            try:
                return cls._to_jsonable(value.to_dict())
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            return cls._to_jsonable(dict(value.__dict__))
        return str(value)

    def _build_run_config(self) -> Optional[RunConfig]:
        if RunConfig is None or OpenAIProvider is None:
            return None
        use_responses = self._use_responses_api()
        azure_endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip()
        if not azure_endpoint:
            return RunConfig(model_provider=OpenAIProvider(use_responses=use_responses))
        if AsyncAzureOpenAI is None:
            raise RuntimeError("openai sdk with azure support is not installed")

        azure_key = (os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        azure_api_version = (os.getenv("AZURE_OPENAI_API_VERSION") or "").strip()
        if not azure_key:
            raise RuntimeError("AZURE_OPENAI_API_KEY is required when AZURE_OPENAI_ENDPOINT is set")
        if not azure_api_version:
            raise RuntimeError("AZURE_OPENAI_API_VERSION is required when AZURE_OPENAI_ENDPOINT is set")

        azure_client = AsyncAzureOpenAI(
            api_key=azure_key,
            azure_endpoint=azure_endpoint,
            api_version=azure_api_version,
        )
        provider = OpenAIProvider(openai_client=azure_client, use_responses=use_responses)
        return RunConfig(model_provider=provider)

    @staticmethod
    def _use_responses_api() -> bool:
        api_mode = (os.getenv("OPENAI_API") or "responses").strip().lower()
        if api_mode in ("", "responses"):
            return True
        if api_mode == "chat_completions":
            return False
        raise RuntimeError("OPENAI_API must be one of: responses, chat_completions")

    def _build_agent(self, config: AgentNodeConfig, model: str) -> Agent:
        tools = self._select_tools(config.allowed_tools)
        output_type = self._output_type(config)
        return Agent(
            name="workflow-agent",
            instructions=config.instructions,
            model=model,
            tools=tools,
            output_type=output_type,
        )

    def _resolve_user_input(self, run, node) -> Optional[str]:
        raw_user_input = node.config.get("user_input", _MISSING)
        if raw_user_input is _MISSING or raw_user_input is None:
            if self._node_expects_json_output(node):
                return self._default_user_input(run)
            return None
        if isinstance(raw_user_input, str):
            return raw_user_input
        normalized = self._to_jsonable(raw_user_input)
        if isinstance(normalized, str):
            return normalized
        return json.dumps(normalized, ensure_ascii=False)

    @classmethod
    def _default_user_input(cls, run) -> str:
        payload = {
            "input": cls._to_jsonable(getattr(run, "inputs", {}) or {}),
            "state": cls._to_jsonable(getattr(run, "state", {}) or {}),
            "node_outputs": cls._to_jsonable(getattr(run, "node_outputs", {}) or {}),
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _output_type(config: AgentNodeConfig) -> Optional[Any]:
        if not AgentExecutor._expects_json_output(config):
            return None
        if not isinstance(config.output_schema, dict) or not config.output_schema:
            return None
        return _RawJSONSchemaOutput(config.output_schema, strict_json_schema=False)

    @staticmethod
    def _node_expects_json_output(node) -> bool:
        raw_format = node.config.get("output_format")
        if isinstance(raw_format, str):
            normalized = raw_format.strip().lower().replace("-", "_")
            if normalized in {"json", "json_schema", "jsonschema"}:
                return True
        if node.config.get("output_schema") is not None and not raw_format:
            return True
        return False

    def _select_tools(self, allowed: Optional[Iterable[str]]) -> List[Any]:
        if not allowed:
            return []
        return [self.tool_registry[name] for name in allowed if name in self.tool_registry]

    @staticmethod
    def _trace_id(run_id: str, node_id: str) -> str:
        digest = hashlib.md5(f"{run_id}:{node_id}".encode()).hexdigest()
        return f"trace_{digest}"

    @staticmethod
    def _expects_json_output(config: AgentNodeConfig) -> bool:
        raw_format = config.output_format
        if isinstance(raw_format, str):
            normalized = raw_format.strip().lower().replace("-", "_")
            if normalized in {"json", "json_schema", "jsonschema"}:
                return True
        if config.output_schema is not None and not raw_format:
            return True
        return False

    @staticmethod
    def _normalize_output(config: AgentNodeConfig, output: Any) -> Any:
        if not AgentExecutor._expects_json_output(config):
            return output
        if not isinstance(output, str):
            return output
        text = output.strip()
        if not text:
            return output
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Agent returned non-JSON output while output_format=json") from exc

    @staticmethod
    def _validate_output(config: AgentNodeConfig, output: Any) -> None:
        if not AgentExecutor._expects_json_output(config):
            return
        if not config.output_schema:
            return
        if jsonschema is None:
            raise RuntimeError("jsonschema is required for output validation")
        jsonschema.validate(instance=output, schema=config.output_schema)
