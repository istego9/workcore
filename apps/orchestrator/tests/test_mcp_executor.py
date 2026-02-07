import unittest

from apps.orchestrator.executors import MCPExecutor, MCPNodeConfig


class FakeClient:
    def call_tool(self, server, tool, arguments, timeout_s, auth=None):
        return {"server": server, "tool": tool, "args": arguments, "timeout": timeout_s}


class MCPExecutorTests(unittest.TestCase):
    def test_mcp_executor_allowlist(self):
        client = FakeClient()
        executor = MCPExecutor(client)
        config = MCPNodeConfig(
            server="local",
            tool="echo",
            arguments={"ping": True},
            allowed_tools=["echo"],
        )
        events = []
        result = executor.execute(config, lambda t, p=None: events.append((t, p)))
        self.assertEqual(result.output["tool"], "echo")
        self.assertTrue(any(evt[0] == "tool_called" for evt in events))

    def test_mcp_executor_blocks_disallowed_tool(self):
        client = FakeClient()
        executor = MCPExecutor(client)
        config = MCPNodeConfig(
            server="local",
            tool="unsafe",
            arguments={},
            allowed_tools=["safe"],
        )
        with self.assertRaises(RuntimeError):
            executor.execute(config, lambda t, p=None: None)


if __name__ == "__main__":
    unittest.main()
