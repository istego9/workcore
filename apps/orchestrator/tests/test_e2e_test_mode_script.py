from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "e2e_test_mode.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("workcore_e2e_test_mode", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeHTTPResponse:
    def __init__(self, payload: bytes = b"{}") -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_request_includes_project_scope_headers(monkeypatch):
    script = _load_script_module()
    captured_headers: dict[str, str] = {}

    def fake_urlopen(req, timeout=10):  # noqa: ARG001
        captured_headers.update({key.lower(): value for key, value in req.header_items()})
        return _FakeHTTPResponse()

    monkeypatch.setenv("E2E_API_AUTH_TOKEN", "token-123")
    monkeypatch.setattr(script.urllib.request, "urlopen", fake_urlopen)

    script._request(
        "http://example.test",
        "/workflows",
        payload={"name": "wf"},
        method="POST",
        headers={"X-Tenant-Id": "local", "X-Project-Id": "proj_ci"},
    )

    assert captured_headers["x-tenant-id"] == "local"
    assert captured_headers["x-project-id"] == "proj_ci"
    assert captured_headers["authorization"] == "Bearer token-123"


def test_main_uses_default_project_scope_headers(monkeypatch):
    script = _load_script_module()
    calls: list[dict[str, object]] = []

    def fake_request(base_url, path, payload=None, method="GET", *, headers=None):  # noqa: ANN001
        calls.append(
            {
                "base_url": base_url,
                "path": path,
                "method": method,
                "headers": dict(headers or {}),
            }
        )
        if path == "/workflows" and method == "POST":
            return {"workflow_id": "wf_test"}
        if path == "/workflows/wf_test/publish" and method == "POST":
            return {"version_id": "wfv_test"}
        if path == "/workflows/wf_test/runs" and method == "POST":
            return {"run_id": "run_test", "mode": "test"}
        if path == "/runs/run_test" and method == "GET":
            return {"run_id": "run_test", "mode": "test"}
        if path == "/workflows/wf_test" and method == "DELETE":
            return {}
        raise AssertionError(f"Unexpected call: {method} {path} payload={payload}")

    monkeypatch.delenv("ORCH_PROJECT_ID", raising=False)
    monkeypatch.delenv("WORKCORE_PROJECT_ID", raising=False)
    monkeypatch.delenv("E2E_PROJECT_ID", raising=False)
    monkeypatch.delenv("ORCH_TENANT_ID", raising=False)
    monkeypatch.delenv("E2E_TENANT_ID", raising=False)
    monkeypatch.setattr(script, "_request", fake_request)

    exit_code = script.main()

    assert exit_code == 0
    assert len(calls) == 5
    first_headers = calls[0]["headers"]
    assert first_headers["X-Tenant-Id"] == "local"
    assert first_headers["X-Project-Id"] == "proj_e2e_test_mode"
