from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _request(
    base_url: str,
    path: str,
    payload: dict | None = None,
    method: str = "GET",
    *,
    headers: dict[str, str] | None = None,
) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if headers:
        for key, value in headers.items():
            if value:
                req.add_header(key, value)
    token = os.getenv("ORCH_AUTH_TOKEN") or os.getenv("WORKCORE_API_AUTH_TOKEN") or os.getenv("E2E_API_AUTH_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"{method} {url} failed: {exc.code} {body}") from exc


def main() -> int:
    base_url = os.getenv("ORCH_BASE_URL", "http://127.0.0.1:8000")
    tenant_id = (os.getenv("ORCH_TENANT_ID") or os.getenv("E2E_TENANT_ID") or "local").strip()
    project_id = (
        os.getenv("ORCH_PROJECT_ID")
        or os.getenv("WORKCORE_PROJECT_ID")
        or os.getenv("E2E_PROJECT_ID")
        or "proj_e2e_test_mode"
    ).strip()
    request_headers = {"X-Tenant-Id": tenant_id, "X-Project-Id": project_id}
    draft = {
        "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}],
        "edges": [{"source": "start", "target": "end"}],
        "variables_schema": {},
    }

    workflow_id: str | None = None
    try:
        workflow = _request(
            base_url,
            "/workflows",
            {"name": "E2E test mode", "draft": draft},
            method="POST",
            headers=request_headers,
        )
        workflow_id = workflow.get("workflow_id")
        if not workflow_id:
            raise RuntimeError(f"Missing workflow_id in response: {workflow}")

        publish = _request(base_url, f"/workflows/{workflow_id}/publish", method="POST", headers=request_headers)
        version_id = publish.get("version_id")
        if not version_id:
            raise RuntimeError(f"Missing version_id in response: {publish}")

        run = _request(
            base_url,
            f"/workflows/{workflow_id}/runs",
            {"inputs": {}, "version_id": version_id, "mode": "test"},
            method="POST",
            headers=request_headers,
        )
        if run.get("mode") != "test":
            raise RuntimeError(f"Expected mode=test in run create response, got: {run}")

        run_id = run.get("run_id")
        if not run_id:
            raise RuntimeError(f"Missing run_id in response: {run}")

        fetched = _request(base_url, f"/runs/{run_id}", headers=request_headers)
        if fetched.get("mode") != "test":
            raise RuntimeError(f"Expected mode=test in run get response, got: {fetched}")

        print("ok: test run mode end-to-end")
        return 0
    finally:
        if workflow_id:
            try:
                _request(base_url, f"/workflows/{workflow_id}", method="DELETE", headers=request_headers)
            except RuntimeError as exc:
                if sys.exc_info()[0] is None:
                    raise
                print(f"cleanup warning: failed to delete workflow {workflow_id}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
