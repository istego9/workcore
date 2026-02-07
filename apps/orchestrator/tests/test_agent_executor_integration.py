import os
import unittest

from agents import set_default_openai_api

from apps.orchestrator.executors import AgentExecutor, AgentNodeConfig
from apps.orchestrator.runtime.env import load_env

load_env()


class AgentExecutorIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL"),
        "Set OPENAI_API_KEY and OPENAI_MODEL to run live integration tests",
    )
    def test_agent_executor_live(self):
        set_default_openai_api(os.environ["OPENAI_API_KEY"])

        executor = AgentExecutor()
        config = AgentNodeConfig(
            model=os.environ["OPENAI_MODEL"],
            instructions="Respond with the exact word 'ok'.",
            user_input="Reply now.",
            emit_partial=False,
        )

        events = []
        result = executor.execute(
            run_id="run_live",
            node_id="agent_live",
            config=config,
            emit=lambda t, p=None: events.append((t, p)),
        )

        self.assertIsNotNone(result.output)
        self.assertTrue(isinstance(result.output, str))
        self.assertIn("ok", result.output.lower())


if __name__ == "__main__":
    unittest.main()
