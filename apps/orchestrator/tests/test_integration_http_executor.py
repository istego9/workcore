import ipaddress
import unittest

from apps.orchestrator.executors.integration_http_executor import IntegrationHTTPEgressPolicy, IntegrationHTTPExecutor
from apps.orchestrator.runtime import Node


class _FakeResponse:
    def __init__(self, status_code: int, body, headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.text = body if isinstance(body, str) else ""

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class _FakeClient:
    def __init__(self, handler):
        self._handler = handler

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def request(self, method, url, **kwargs):
        return self._handler(method, url, **kwargs)


class IntegrationHTTPExecutorTests(unittest.TestCase):
    @staticmethod
    def _policy(
        *allowed_hosts: str,
        allow_private_networks: bool = False,
        deny_cidrs=(),
        resolver=None,
    ) -> IntegrationHTTPEgressPolicy:
        return IntegrationHTTPEgressPolicy(
            allowed_hosts=allowed_hosts,
            allowed_schemes=("https",),
            allow_private_networks=allow_private_networks,
            deny_cidrs=deny_cidrs,
            host_resolver=resolver or (lambda _host: ("1.1.1.1",)),
        )

    def test_executor_applies_bearer_auth_and_returns_body(self):
        captured = {"headers": None, "method": None, "url": None}

        def handler(method, url, **kwargs):
            captured["headers"] = dict(kwargs.get("headers") or {})
            captured["method"] = method
            captured["url"] = url
            return _FakeResponse(200, {"ok": True}, headers={"content-type": "application/json"})

        executor = IntegrationHTTPExecutor(
            client_factory=lambda timeout: _FakeClient(handler),
            egress_policy=self._policy("api.example.com"),
        )
        node = Node(
            "http",
            "integration_http",
            {
                "url": "https://api.example.com/v1/ping",
                "method": "GET",
                "auth": {"type": "bearer", "token": "secret_token"},
            },
        )
        emitted = []
        result = executor(None, node, lambda event_type, payload=None: emitted.append((event_type, payload)))

        self.assertEqual(captured["method"], "GET")
        self.assertEqual(captured["url"], "https://api.example.com/v1/ping")
        self.assertEqual(captured["headers"].get("Authorization"), "Bearer secret_token")
        self.assertEqual(result.output["status_code"], 200)
        self.assertEqual(result.output["body"], {"ok": True})
        self.assertTrue(any(event[0] == "integration_http_called" for event in emitted))

    def test_executor_retries_on_failure(self):
        attempts = {"count": 0}

        def handler(method, url, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("temporary failure")
            return _FakeResponse(200, {"ok": True})

        executor = IntegrationHTTPExecutor(
            client_factory=lambda timeout: _FakeClient(handler),
            egress_policy=self._policy("api.example.com"),
        )
        node = Node(
            "http",
            "integration_http",
            {
                "url": "https://api.example.com/v1/retry",
                "method": "POST",
                "retry_attempts": 1,
                "retry_backoff_s": 0,
                "request_body": {"probe": True},
            },
        )
        result = executor(None, node, lambda *_: None)

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(result.output["status_code"], 200)

    def test_executor_rejects_unexpected_status_when_fail_on_status_enabled(self):
        def handler(method, url, **kwargs):
            return _FakeResponse(500, {"error": "boom"})

        executor = IntegrationHTTPExecutor(
            client_factory=lambda timeout: _FakeClient(handler),
            egress_policy=self._policy("api.example.com"),
        )
        node = Node(
            "http",
            "integration_http",
            {
                "url": "https://api.example.com/v1/fail",
                "method": "GET",
                "retry_attempts": 0,
                "fail_on_status": True,
            },
        )

        with self.assertRaises(RuntimeError):
            executor(None, node, lambda *_: None)

    def test_executor_rejects_disallowed_host_by_egress_policy(self):
        executor = IntegrationHTTPExecutor(
            client_factory=lambda timeout: _FakeClient(lambda *_args, **_kwargs: _FakeResponse(200, {"ok": True})),
            egress_policy=self._policy("api.example.com"),
        )
        node = Node(
            "http",
            "integration_http",
            {
                "url": "https://evil.example.net/v1/probe",
                "method": "GET",
            },
        )

        with self.assertRaises(RuntimeError):
            executor(None, node, lambda *_: None)

    def test_executor_rejects_private_network_host_by_default(self):
        executor = IntegrationHTTPExecutor(
            client_factory=lambda timeout: _FakeClient(lambda *_args, **_kwargs: _FakeResponse(200, {"ok": True})),
            egress_policy=self._policy("127.0.0.1"),
        )
        node = Node(
            "http",
            "integration_http",
            {
                "url": "https://127.0.0.1/internal",
                "method": "GET",
            },
        )

        with self.assertRaises(RuntimeError):
            executor(None, node, lambda *_: None)

    def test_executor_allows_private_network_when_explicitly_enabled(self):
        executor = IntegrationHTTPExecutor(
            client_factory=lambda timeout: _FakeClient(lambda *_args, **_kwargs: _FakeResponse(200, {"ok": True})),
            egress_policy=self._policy("127.0.0.1", allow_private_networks=True),
        )
        node = Node(
            "http",
            "integration_http",
            {
                "url": "https://127.0.0.1/internal",
                "method": "GET",
            },
        )

        result = executor(None, node, lambda *_: None)
        self.assertEqual(result.output["status_code"], 200)

    def test_executor_rejects_host_when_dns_resolves_to_private_address(self):
        executor = IntegrationHTTPExecutor(
            client_factory=lambda timeout: _FakeClient(lambda *_args, **_kwargs: _FakeResponse(200, {"ok": True})),
            egress_policy=self._policy(
                "api.example.com",
                resolver=lambda _host: ("10.20.30.40",),
            ),
        )
        node = Node(
            "http",
            "integration_http",
            {
                "url": "https://api.example.com/internal",
                "method": "GET",
            },
        )

        with self.assertRaises(RuntimeError):
            executor(None, node, lambda *_: None)

    def test_executor_rejects_host_when_dns_resolves_to_denied_cidr(self):
        executor = IntegrationHTTPExecutor(
            client_factory=lambda timeout: _FakeClient(lambda *_args, **_kwargs: _FakeResponse(200, {"ok": True})),
            egress_policy=self._policy(
                "api.example.com",
                deny_cidrs=(
                    ipaddress.ip_network("34.0.0.0/8"),
                    ipaddress.ip_network("2001:db8::/32"),
                ),
                resolver=lambda _host: ("34.10.11.12",),
            ),
        )
        node = Node(
            "http",
            "integration_http",
            {
                "url": "https://api.example.com/v1/data",
                "method": "GET",
            },
        )

        with self.assertRaises(RuntimeError):
            executor(None, node, lambda *_: None)

    def test_executor_allows_private_dns_target_when_explicitly_enabled(self):
        executor = IntegrationHTTPExecutor(
            client_factory=lambda timeout: _FakeClient(lambda *_args, **_kwargs: _FakeResponse(200, {"ok": True})),
            egress_policy=self._policy(
                "api.example.com",
                allow_private_networks=True,
                resolver=lambda _host: ("10.20.30.40",),
            ),
        )
        node = Node(
            "http",
            "integration_http",
            {
                "url": "https://api.example.com/internal",
                "method": "GET",
            },
        )

        result = executor(None, node, lambda *_: None)
        self.assertEqual(result.output["status_code"], 200)


if __name__ == "__main__":
    unittest.main()
