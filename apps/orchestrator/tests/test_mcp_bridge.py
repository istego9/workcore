import unittest

from starlette.testclient import TestClient

from apps.orchestrator.executors.mcp_bridge_client import MCPBridgeClientConfig, MCPBridgeHttpClient, UnconfiguredMCPClient, mcp_client_from_env
from apps.orchestrator.mcp_bridge.service import MCPBridgeConfig, create_app


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.content = str(payload).encode("utf-8")

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.last_payload = None
        self.last_headers = None
        self.last_url = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json=None, headers=None):
        self.last_url = url
        self.last_payload = json
        self.last_headers = headers
        return self._response


class MCPBridgeClientTests(unittest.TestCase):
    def test_unconfigured_client_raises_explicit_error(self):
        client = UnconfiguredMCPClient()
        with self.assertRaises(RuntimeError):
            client.call_tool("local", "echo", {}, 10.0)

    def test_client_posts_to_internal_bridge_and_returns_result(self):
        fake_http_client = _FakeClient(_FakeResponse(200, {"result": {"ok": True}}))
        client = MCPBridgeHttpClient(
            MCPBridgeClientConfig(base_url="http://bridge.local", auth_token="token"),
            client_factory=lambda timeout: fake_http_client,
        )

        result = client.call_tool(
            server="local",
            tool="echo",
            arguments={"ping": True},
            timeout_s=15,
            metadata={"run_id": "run_1"},
        )
        self.assertEqual(result["ok"], True)
        self.assertEqual(fake_http_client.last_url, "http://bridge.local/internal/mcp/call")
        self.assertEqual(fake_http_client.last_payload["tool"], "echo")
        self.assertEqual(fake_http_client.last_headers["Authorization"], "Bearer token")

    def test_client_raises_on_bridge_error_response(self):
        fake_http_client = _FakeClient(_FakeResponse(503, {"error": {"message": "not configured"}}))
        client = MCPBridgeHttpClient(
            MCPBridgeClientConfig(base_url="http://bridge.local"),
            client_factory=lambda timeout: fake_http_client,
        )
        with self.assertRaises(RuntimeError):
            client.call_tool("local", "echo", {}, 5.0)

    def test_mcp_client_from_env_returns_unconfigured_when_base_url_missing(self):
        client = mcp_client_from_env(lambda *_: "")
        self.assertIsInstance(client, UnconfiguredMCPClient)


class MCPBridgeServiceTests(unittest.TestCase):
    def test_bridge_requires_auth_token_when_configured(self):
        config = MCPBridgeConfig(
            auth_token="bridge_token",
            upstream_call_url=None,
            upstream_auth_token=None,
            request_timeout_s=30.0,
            max_timeout_s=120.0,
            max_arguments_bytes=1024 * 1024,
            allowed_servers=(),
            allowed_tools=(),
        )
        app = create_app(config=config, tool_caller=lambda *_: {"ok": True})
        client = TestClient(app)
        response = client.post(
            "/internal/mcp/call",
            json={"server": "local", "tool": "echo", "arguments": {}, "timeout_s": 10},
        )
        self.assertEqual(response.status_code, 401)

    def test_bridge_returns_result_for_valid_request(self):
        config = MCPBridgeConfig(
            auth_token=None,
            upstream_call_url=None,
            upstream_auth_token=None,
            request_timeout_s=30.0,
            max_timeout_s=120.0,
            max_arguments_bytes=1024 * 1024,
            allowed_servers=(),
            allowed_tools=(),
        )
        captured = {}

        def fake_caller(server, tool, arguments, timeout_s, auth, metadata):
            captured["server"] = server
            captured["tool"] = tool
            captured["metadata"] = metadata
            return {"ok": True}

        app = create_app(config=config, tool_caller=fake_caller)
        client = TestClient(app)
        response = client.post(
            "/internal/mcp/call",
            json={
                "server": "local",
                "tool": "echo",
                "arguments": {"ping": True},
                "timeout_s": 10,
                "metadata": {"run_id": "run_1"},
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["ok"], True)
        self.assertEqual(captured["server"], "local")
        self.assertEqual(captured["tool"], "echo")
        self.assertEqual(captured["metadata"]["run_id"], "run_1")

    def test_bridge_returns_503_when_upstream_not_configured(self):
        config = MCPBridgeConfig(
            auth_token=None,
            upstream_call_url=None,
            upstream_auth_token=None,
            request_timeout_s=30.0,
            max_timeout_s=120.0,
            max_arguments_bytes=1024 * 1024,
            allowed_servers=(),
            allowed_tools=(),
        )
        app = create_app(config=config)
        client = TestClient(app)
        response = client.post(
            "/internal/mcp/call",
            json={"server": "local", "tool": "echo", "arguments": {}, "timeout_s": 10},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "PRECONDITION_FAILED")

    def test_bridge_rejects_disallowed_tool(self):
        config = MCPBridgeConfig(
            auth_token=None,
            upstream_call_url=None,
            upstream_auth_token=None,
            request_timeout_s=30.0,
            max_timeout_s=120.0,
            max_arguments_bytes=1024 * 1024,
            allowed_servers=("local",),
            allowed_tools=("safe",),
        )
        app = create_app(config=config, tool_caller=lambda *_: {"ok": True})
        client = TestClient(app)
        response = client.post(
            "/internal/mcp/call",
            json={"server": "local", "tool": "echo", "arguments": {}, "timeout_s": 10},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
