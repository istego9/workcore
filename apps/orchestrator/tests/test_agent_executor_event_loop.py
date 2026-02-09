import asyncio
import unittest
from types import SimpleNamespace

from agents.usage import Usage
from apps.orchestrator.executors.agent_executor import AgentExecutor, AgentNodeConfig


class FakeAgentExecutor(AgentExecutor):
    def _build_agent(self, config, model):  # type: ignore[override]
        return object()

    async def _run_streamed(self, agent, config, emit):  # type: ignore[override]
        emit("message_generated", {"text": "hi"})
        return {"ok": True}


class FakeUsageAgentExecutor(AgentExecutor):
    def _build_agent(self, config, model):  # type: ignore[override]
        return object()

    async def _run_streamed(self, agent, config, emit):  # type: ignore[override]
        usage = Usage(requests=1, input_tokens=10, output_tokens=7, total_tokens=17)
        return SimpleNamespace(
            final_output={"ok": True},
            context_wrapper=SimpleNamespace(usage=usage),
        )


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


if __name__ == "__main__":
    unittest.main()
