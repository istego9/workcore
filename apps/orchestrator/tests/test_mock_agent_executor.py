import unittest
from types import SimpleNamespace

from apps.orchestrator.executors.mock_agent_executor import MockAgentExecutor


class MockAgentExecutorTests(unittest.TestCase):
    def test_mock_executor_returns_estimated_usage(self):
        executor = MockAgentExecutor()
        node = SimpleNamespace(
            config={
                "instructions": "Extract data from uploaded document.",
                "user_input": "Policy submission payload",
            }
        )
        run = SimpleNamespace(id="run_mock")
        emitted = []

        result = executor(run, node, lambda t, p=None: emitted.append((t, p)))

        self.assertEqual(result.output.get("mock"), True)
        self.assertIsInstance(result.usage, dict)
        usage = result.usage or {}
        self.assertEqual(usage.get("provider"), "mock")
        self.assertEqual(usage.get("estimated"), True)
        self.assertGreater(usage.get("input_tokens", 0), 0)
        self.assertGreater(usage.get("output_tokens", 0), 0)
        self.assertEqual(
            usage.get("total_tokens"),
            usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        )


if __name__ == "__main__":
    unittest.main()
