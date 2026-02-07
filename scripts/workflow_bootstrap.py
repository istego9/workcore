from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.orchestrator.api.workflow_store import (
    InMemoryWorkflowStore,
    create_workflow_store,
)


DEFAULT_DRAFT = {
    "nodes": [
        {"id": "start", "type": "start", "config": {"defaults": {}}},
        {"id": "end", "type": "end", "config": {}},
    ],
    "edges": [{"source": "start", "target": "end"}],
    "variables_schema": {},
}


def _load_draft(path: str | None) -> dict:
    if not path:
        return DEFAULT_DRAFT
    draft_path = Path(path)
    data = json.loads(draft_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("draft file must contain a JSON object")
    return data


async def _run(args: argparse.Namespace) -> int:
    load_dotenv()
    if not (os.getenv("DATABASE_URL") or os.getenv("CHATKIT_DATABASE_URL")):
        print("DATABASE_URL or CHATKIT_DATABASE_URL is required.")
        return 1

    store = await create_workflow_store()
    if isinstance(store, InMemoryWorkflowStore):
        print("Database URL not configured; refusing to create workflow in memory.")
        return 1

    draft = _load_draft(args.draft)
    workflow = await store.create_workflow(
        name=args.name,
        description=args.description,
        draft=draft,
    )
    version = await store.publish(workflow.workflow_id)
    await store.close()

    print(f"workflow_id={workflow.workflow_id}")
    print(f"version_id={version.version_id}")
    print("")
    print("Example:")
    print(
        "CHATKIT_WORKFLOW_ID={workflow_id} CHATKIT_WORKFLOW_VERSION_ID={version_id} "
        "./.venv/bin/python scripts/chatkit_e2e.py".format(
            workflow_id=workflow.workflow_id,
            version_id=version.version_id,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and publish a workflow for local dev.")
    parser.add_argument("--name", default="Bootstrap workflow")
    parser.add_argument("--description", default="Created by workflow_bootstrap.py")
    parser.add_argument("--draft", help="Path to a JSON draft file")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
