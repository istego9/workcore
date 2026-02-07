from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _request(base_url: str, path: str, payload: dict | None = None, method: str = "GET") -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"{method} {url} failed: {exc.code} {body}") from exc


def main() -> int:
    base_url = os.getenv("ORCH_BASE_URL", "http://127.0.0.1:8000")
    draft = {
        "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}],
        "edges": [{"source": "start", "target": "end"}],
        "variables_schema": {},
    }

    workflow = _request(base_url, "/workflows", {"name": "E2E test mode", "draft": draft}, method="POST")
    workflow_id = workflow.get("workflow_id")
    if not workflow_id:
        raise RuntimeError(f"Missing workflow_id in response: {workflow}")

    publish = _request(base_url, f"/workflows/{workflow_id}/publish", method="POST")
    version_id = publish.get("version_id")
    if not version_id:
        raise RuntimeError(f"Missing version_id in response: {publish}")

    run = _request(
        base_url,
        f"/workflows/{workflow_id}/runs",
        {"inputs": {}, "version_id": version_id, "mode": "test"},
        method="POST",
    )
    if run.get("mode") != "test":
        raise RuntimeError(f"Expected mode=test in run create response, got: {run}")

    run_id = run.get("run_id")
    if not run_id:
        raise RuntimeError(f"Missing run_id in response: {run}")

    fetched = _request(base_url, f"/runs/{run_id}")
    if fetched.get("mode") != "test":
        raise RuntimeError(f"Expected mode=test in run get response, got: {fetched}")

    print("ok: test run mode end-to-end")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
