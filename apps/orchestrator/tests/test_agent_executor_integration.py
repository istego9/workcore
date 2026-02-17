import os
import unittest

from apps.orchestrator.executors import AgentExecutor, AgentNodeConfig
from apps.orchestrator.runtime.env import load_env

load_env()


def _has_live_llm_env() -> bool:
    has_model = bool(os.getenv("OPENAI_MODEL"))
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    has_azure = bool(
        os.getenv("AZURE_OPENAI_ENDPOINT")
        and os.getenv("AZURE_OPENAI_API_KEY")
        and os.getenv("AZURE_OPENAI_API_VERSION")
    )
    return has_model and (has_openai or has_azure)


class AgentExecutorIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(
        _has_live_llm_env(),
        "Set OPENAI_MODEL and either OpenAI or Azure OpenAI credentials to run live integration tests",
    )
    def test_agent_executor_live(self):
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
