import unittest

from apps.orchestrator.executors import MCPExecutor, MCPNodeConfig


class FakeClient:
    def __init__(self):
        self.last_metadata = None

    def call_tool(self, server, tool, arguments, timeout_s, auth=None, metadata=None):
        self.last_metadata = metadata
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

    def test_mcp_executor_callable_parses_node_config_and_forwards_metadata(self):
        client = FakeClient()
        executor = MCPExecutor(client)
        run = type(
            "RunStub",
            (),
            {
                "id": "run_1",
                "metadata": {"correlation_id": "corr_1", "trace_id": "trace_1", "tenant_id": "tenant_local"},
            },
        )()
        node = type(
            "NodeStub",
            (),
            {
                "id": "node_mcp",
                "config": {
                    "server": "local",
                    "tool": "echo",
                    "arguments": {"ping": True},
                    "timeout_s": 25,
                },
            },
        )()
        result = executor(run, node, lambda *_: None)
        self.assertEqual(result.output["tool"], "echo")
        self.assertIsInstance(client.last_metadata, dict)
        self.assertEqual(client.last_metadata["run_id"], "run_1")
        self.assertEqual(client.last_metadata["node_id"], "node_mcp")
        self.assertEqual(client.last_metadata["correlation_id"], "corr_1")

    def test_mcp_executor_callable_rejects_missing_server(self):
        executor = MCPExecutor(FakeClient())
        node = type("NodeStub", (), {"id": "node_mcp", "config": {"tool": "echo"}})()
        with self.assertRaises(RuntimeError):
            executor(None, node, lambda *_: None)


if __name__ == "__main__":
    unittest.main()
