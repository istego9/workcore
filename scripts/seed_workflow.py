from __future__ import annotations

import asyncio
import os
import uuid
import json

import asyncpg
from dotenv import load_dotenv


WORKFLOW_TEMPLATE = {
    "nodes": [
        {"id": "start", "type": "start", "config": {"defaults": {}}},
        {"id": "approval", "type": "approval", "config": {"prompt": "Approve the request?"}},
        {"id": "end", "type": "end", "config": {}},
    ],
    "edges": [
        {"source": "start", "target": "approval"},
        {"source": "approval", "target": "end"},
    ],
}


def _load_database_url() -> str:
    load_dotenv()
    url = os.getenv("DATABASE_URL") or os.getenv("CHATKIT_DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL or CHATKIT_DATABASE_URL is required")
    return url


async def main() -> None:
    database_url = _load_database_url()
    workflow_id = f"wf_{uuid.uuid4().hex[:8]}"
    version_id = f"wfv_{uuid.uuid4().hex[:8]}"

    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(
            """
            insert into workflows (id, tenant_id, name, description, draft, active_version_id)
            values ($1, $2, $3, $4, $5::jsonb, $6)
            """,
            workflow_id,
            "local",
            "ChatKit Approval Flow",
            "Start -> Approval -> End",
            json.dumps(WORKFLOW_TEMPLATE),
            None,
        )
        await conn.execute(
            """
            insert into workflow_versions (id, workflow_id, tenant_id, version_number, hash, content)
            values ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            version_id,
            workflow_id,
            "local",
            1,
            f"hash_{uuid.uuid4().hex[:12]}",
            json.dumps(WORKFLOW_TEMPLATE),
        )
        await conn.execute(
            """
            update workflows set active_version_id = $1 where id = $2
            """,
            version_id,
            workflow_id,
        )
    finally:
        await conn.close()

    print(f"workflow_id={workflow_id}")
    print(f"version_id={version_id}")


if __name__ == "__main__":
    asyncio.run(main())
