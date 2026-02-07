import asyncio
import unittest

from apps.orchestrator.executors.agent_executor import AgentExecutor, AgentNodeConfig


class FakeAgentExecutor(AgentExecutor):
    def _build_agent(self, config, model):  # type: ignore[override]
        return object()

    async def _run_streamed(self, agent, config, emit):  # type: ignore[override]
        emit("message_generated", {"text": "hi"})
        return {"ok": True}


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


if __name__ == "__main__":
    unittest.main()
