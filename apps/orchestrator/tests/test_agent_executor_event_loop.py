import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from agents import AgentOutputSchemaBase
from agents.usage import Usage
from apps.orchestrator.executors.agent_executor import AgentExecutor, AgentNodeConfig


class FakeAgentExecutor(AgentExecutor):
    def _build_agent(self, config, model):  # type: ignore[override]
        return object()

    async def _run_streamed(self, agent, config, emit, run_config):  # type: ignore[override]
        emit("message_generated", {"text": "hi"})
        return {"ok": True}


class FakeUsageAgentExecutor(AgentExecutor):
    def _build_agent(self, config, model):  # type: ignore[override]
        return object()

    async def _run_streamed(self, agent, config, emit, run_config):  # type: ignore[override]
        usage = Usage(requests=1, input_tokens=10, output_tokens=7, total_tokens=17)
        return SimpleNamespace(
            final_output={"ok": True},
            context_wrapper=SimpleNamespace(usage=usage),
        )


class FakeJsonStringAgentExecutor(AgentExecutor):
    def _build_agent(self, config, model):  # type: ignore[override]
        return object()

    async def _run_streamed(self, agent, config, emit, run_config):  # type: ignore[override]
        return '{"ok": true}'


class FakeInvalidJsonStringAgentExecutor(AgentExecutor):
    def _build_agent(self, config, model):  # type: ignore[override]
        return object()

    async def _run_streamed(self, agent, config, emit, run_config):  # type: ignore[override]
        return "not-json"


class CaptureConfigAgentExecutor(AgentExecutor):
    captured_config: AgentNodeConfig | None = None

    def _build_agent(self, config, model):  # type: ignore[override]
        return object()

    async def _run_streamed(self, agent, config, emit, run_config):  # type: ignore[override]
        self.captured_config = config
        return '{"ok": true}'


class AgentExecutorLoopTests(unittest.TestCase):
    def test_execute_inside_running_loop(self):
        executor = FakeAgentExecutor()
        config = AgentNodeConfig(
            instructions="Hello",
            user_input="Test",
            emit_partial=False,
        )

        async def runner():
            result = executor.execute(
                run_id="run_loop",
                node_id="agent_loop",
                config=config,
                emit=lambda t, p=None: None,
            )
            return result.output

        output = asyncio.run(runner())
        self.assertEqual(output, {"ok": True})

    def test_execute_extracts_usage(self):
        executor = FakeUsageAgentExecutor()
        config = AgentNodeConfig(
            instructions="Hello",
            user_input="Test",
            emit_partial=False,
        )
        result = executor.execute(
            run_id="run_usage",
            node_id="agent_usage",
            config=config,
            emit=lambda t, p=None: None,
        )

        self.assertEqual(result.output, {"ok": True})
        self.assertIsInstance(result.usage, dict)
        usage = result.usage or {}
        self.assertEqual(usage.get("input_tokens"), 10)
        self.assertEqual(usage.get("output_tokens"), 7)
        self.assertEqual(usage.get("total_tokens"), 17)
        self.assertEqual(usage.get("input_tokens_details"), {"cached_tokens": 0})
        self.assertEqual(usage.get("output_tokens_details"), {"reasoning_tokens": 0})

    def test_build_run_config_uses_chat_completions_when_requested(self):
        executor = FakeAgentExecutor()
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_API": "chat_completions",
                "AZURE_OPENAI_ENDPOINT": "",
                "AZURE_OPENAI_API_KEY": "",
                "AZURE_OPENAI_API_VERSION": "",
            },
            clear=False,
        ):
            run_config = executor._build_run_config()
        self.assertIsNotNone(run_config)
        provider = run_config.model_provider if run_config else None
        self.assertFalse(getattr(provider, "_use_responses"))

    def test_build_run_config_azure_requires_api_version(self):
        executor = FakeAgentExecutor()
        with mock.patch.dict(
            os.environ,
            {
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
                "AZURE_OPENAI_API_KEY": "azure_test_key",
                "AZURE_OPENAI_API_VERSION": "",
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                executor._build_run_config()

    def test_build_run_config_rejects_invalid_openai_api_mode(self):
        executor = FakeAgentExecutor()
        with mock.patch.dict(os.environ, {"OPENAI_API": "invalid_mode"}, clear=False):
            with self.assertRaises(RuntimeError):
                executor._build_run_config()

    def test_execute_parses_json_string_output(self):
        executor = FakeJsonStringAgentExecutor()
        config = AgentNodeConfig(
            instructions="Return JSON",
            user_input="now",
            output_format="json",
            output_schema={
                "type": "object",
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
                "additionalProperties": False,
            },
            emit_partial=False,
        )
        result = executor.execute(
            run_id="run_json_parse",
            node_id="agent_json_parse",
            config=config,
            emit=lambda t, p=None: None,
        )
        self.assertEqual(result.output, {"ok": True})

    def test_execute_rejects_invalid_json_string_output(self):
        executor = FakeInvalidJsonStringAgentExecutor()
        config = AgentNodeConfig(
            instructions="Return JSON",
            user_input="now",
            output_format="json",
            emit_partial=False,
        )
        with self.assertRaises(RuntimeError):
            executor.execute(
                run_id="run_json_invalid",
                node_id="agent_json_invalid",
                config=config,
                emit=lambda t, p=None: None,
            )

    def test_execute_parses_json_string_for_json_schema_format(self):
        executor = FakeJsonStringAgentExecutor()
        config = AgentNodeConfig(
            instructions="Return JSON",
            user_input="now",
            output_format="json_schema",
            output_schema={
                "type": "object",
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
                "additionalProperties": False,
            },
            emit_partial=False,
        )
        result = executor.execute(
            run_id="run_json_schema_parse",
            node_id="agent_json_schema_parse",
            config=config,
            emit=lambda t, p=None: None,
        )
        self.assertEqual(result.output, {"ok": True})

    def test_execute_parses_json_string_when_output_schema_set_without_format(self):
        executor = FakeJsonStringAgentExecutor()
        config = AgentNodeConfig(
            instructions="Return JSON",
            user_input="now",
            output_format=None,
            output_schema={
                "type": "object",
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
                "additionalProperties": False,
            },
            emit_partial=False,
        )
        result = executor.execute(
            run_id="run_json_schema_only_parse",
            node_id="agent_json_schema_only_parse",
            config=config,
            emit=lambda t, p=None: None,
        )
        self.assertEqual(result.output, {"ok": True})

    def test_call_uses_context_payload_when_user_input_is_missing(self):
        executor = CaptureConfigAgentExecutor()
        run = SimpleNamespace(
            id="run_missing_user_input",
            inputs={"documents": [{"doc_id": "doc_1"}]},
            state={"phase": "classification"},
            node_outputs={"start": {"phase": "classification"}},
        )
        node = SimpleNamespace(
            id="agent_missing_user_input",
            config={
                "instructions": "Return JSON",
                "output_format": "json_schema",
                "output_schema": {
                    "type": "object",
                    "required": ["ok"],
                    "properties": {"ok": {"type": "boolean"}},
                    "additionalProperties": False,
                },
                "emit_partial": False,
            },
        )
        result = executor(run, node, emit=lambda *_: None)

        self.assertEqual(result.output, {"ok": True})
        captured = executor.captured_config
        self.assertIsNotNone(captured)
        payload = json.loads(captured.user_input or "{}")
        self.assertEqual(payload.get("input"), run.inputs)
        self.assertEqual(payload.get("state"), run.state)
        self.assertEqual(payload.get("node_outputs"), run.node_outputs)

    def test_call_keeps_empty_input_when_user_input_is_missing_for_text_mode(self):
        executor = CaptureConfigAgentExecutor()
        run = SimpleNamespace(
            id="run_missing_user_input_text",
            inputs={"documents": [{"doc_id": "doc_1"}]},
            state={"phase": "classification"},
            node_outputs={"start": {"phase": "classification"}},
        )
        node = SimpleNamespace(
            id="agent_missing_user_input_text",
            config={
                "instructions": "Return text",
                "emit_partial": False,
            },
        )
        result = executor(run, node, emit=lambda *_: None)

        self.assertEqual(result.output, '{"ok": true}')
        captured = executor.captured_config
        self.assertIsNotNone(captured)
        self.assertIsNone(captured.user_input)

    def test_build_agent_attaches_output_schema_to_model_output_type(self):
        executor = AgentExecutor()
        output_schema = {
            "type": "object",
            "required": ["ok"],
            "properties": {"ok": {"type": "boolean"}},
            "additionalProperties": False,
        }
        config = AgentNodeConfig(
            instructions="Return JSON",
            user_input="{}",
            output_format="json_schema",
            output_schema=output_schema,
            emit_partial=False,
        )

        agent = executor._build_agent(config, "gpt-5.2")
        output_type = getattr(agent, "output_type", None)
        self.assertIsNotNone(output_type)
        self.assertIsInstance(output_type, AgentOutputSchemaBase)
        self.assertEqual(output_type.json_schema(), output_schema)


if __name__ == "__main__":
    unittest.main()
