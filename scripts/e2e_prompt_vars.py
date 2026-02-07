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


def _agent_output(run_payload: dict) -> dict:
    for item in run_payload.get("node_runs", []):
        if item.get("node_id") == "agent":
            return item.get("output") or {}
    return {}


def main() -> int:
    base_url = os.getenv("ORCH_BASE_URL", "http://127.0.0.1:8000")
    draft = {
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "set", "type": "set_state", "config": {"target": "user", "expression": "inputs['user']"}},
            {
                "id": "agent",
                "type": "agent",
                "config": {
                    "instructions": "Hello {{state['user']}} from {{inputs['source']}} prev={{node_outputs['set']}}",
                    "user_input": "order {{inputs['order_id']}}",
                    "emit_partial": False,
                },
            },
            {"id": "end", "type": "end"},
        ],
        "edges": [
            {"source": "start", "target": "set"},
            {"source": "set", "target": "agent"},
            {"source": "agent", "target": "end"},
        ],
        "variables_schema": {},
    }

    workflow = _request(base_url, "/workflows", {"name": "E2E prompt vars", "draft": draft}, method="POST")
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
        {
            "inputs": {"user": "Alice", "source": "webhook", "order_id": 42},
            "version_id": version_id,
            "mode": "test",
        },
        method="POST",
    )
    run_id = run.get("run_id")
    if not run_id:
        raise RuntimeError(f"Missing run_id in response: {run}")

    fetched = _request(base_url, f"/runs/{run_id}")
    output = _agent_output(fetched)
    if isinstance(output, dict):
        if output.get("resolved_instructions") != "Hello Alice from webhook prev=Alice":
            raise RuntimeError(f"Unexpected resolved instructions: {output}")
        if output.get("resolved_input") != "order 42":
            raise RuntimeError(f"Unexpected resolved input: {output}")
    elif isinstance(output, str):
        if not output.strip():
            raise RuntimeError("Agent returned an empty string output")
    else:
        raise RuntimeError(f"Unexpected agent output type: {type(output).__name__}")

    print("ok: prompt variables resolved end-to-end")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
