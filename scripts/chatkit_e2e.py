from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

import httpx

from chatkit.actions import Action
from chatkit.types import (
    InferenceOptions,
    ThreadCreateParams,
    ThreadCustomActionParams,
    ThreadsCreateReq,
    ThreadsCustomActionReq,
    UserMessageInput,
    UserMessageTextContent,
)


def _stream_events(response: httpx.Response) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for line in response.iter_lines():
        if not line:
            continue
        if line.startswith("data: "):
            payload = json.loads(line[len("data: ") :])
            events.append(payload)
    return events


def _find_action_payload(events: List[Dict[str, Any]], action_type: str) -> Optional[Dict[str, Any]]:
    for event in events:
        if event.get("type") != "thread.item.done":
            continue
        item = event.get("item", {})
        if item.get("type") != "widget":
            continue
        widget = item.get("widget", {})
        payload = _find_action_in_widget(widget, action_type)
        if payload:
            return payload
    return None


def _find_action_in_widget(node: Any, action_type: str) -> Optional[Dict[str, Any]]:
    if isinstance(node, dict):
        for key in ("onClickAction", "onSubmitAction"):
            action = node.get(key)
            if isinstance(action, dict) and action.get("type") == action_type:
                return action.get("payload")
        for value in node.values():
            found = _find_action_in_widget(value, action_type)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_action_in_widget(value, action_type)
            if found:
                return found
    return None


def _completed(events: List[Dict[str, Any]]) -> bool:
    for event in events:
        if event.get("type") == "progress_update":
            if "completed" in event.get("text", "").lower():
                return True
        if event.get("type") == "thread.item.done":
            item = event.get("item", {})
            if item.get("type") == "assistant_message":
                content = item.get("content") or []
                for part in content:
                    if "completed" in part.get("text", "").lower():
                        return True
    return False


def main() -> int:
    base_url = os.getenv("CHATKIT_BASE_URL", "http://localhost:8001")
    token = os.getenv("CHATKIT_AUTH_TOKEN", "")
    workflow_id = os.getenv("CHATKIT_WORKFLOW_ID")
    workflow_version_id = os.getenv("CHATKIT_WORKFLOW_VERSION_ID")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    if not workflow_id:
        print("CHATKIT_WORKFLOW_ID is required (pass via metadata on threads.create).", file=sys.stderr)
        return 1

    metadata = {"workflow_id": workflow_id}
    if workflow_version_id:
        metadata["workflow_version_id"] = workflow_version_id

    req = ThreadsCreateReq(
        metadata=metadata,
        params=ThreadCreateParams(
            input=UserMessageInput(
                content=[UserMessageTextContent(text="start")],
                attachments=[],
                inference_options=InferenceOptions(),
            )
        )
    )

    with httpx.Client(timeout=30) as client:
        with client.stream("POST", f"{base_url}/chatkit", content=req.model_dump_json(), headers=headers) as resp:
            resp.raise_for_status()
            events = _stream_events(resp)

        thread_id = None
        for event in events:
            if event.get("type") == "thread.created":
                thread_id = event["thread"]["id"]
                break
        if not thread_id:
            print("No thread created event found", file=sys.stderr)
            return 1

        payload = _find_action_payload(events, "interrupt.approve")
        if not payload:
            print("No interrupt.approve action found", file=sys.stderr)
            return 1

        action_req = ThreadsCustomActionReq(
            params=ThreadCustomActionParams(
                thread_id=thread_id,
                item_id=None,
                action=Action(type="interrupt.approve", payload=payload),
            )
        )

        with client.stream(
            "POST",
            f"{base_url}/chatkit",
            content=action_req.model_dump_json(),
            headers=headers,
        ) as resp:
            resp.raise_for_status()
            action_events = _stream_events(resp)

    if not _completed(action_events):
        print("Run did not complete", file=sys.stderr)
        return 1

    print("ChatKit E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
