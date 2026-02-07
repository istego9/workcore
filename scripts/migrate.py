from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv


def _get_database_url() -> str | None:
    load_dotenv()
    return os.getenv("DATABASE_URL") or os.getenv("CHATKIT_DATABASE_URL")


async def _run() -> int:
    database_url = _get_database_url()
    if not database_url:
        print("DATABASE_URL or CHATKIT_DATABASE_URL is required", file=sys.stderr)
        return 1

    migrations_dir = Path(__file__).resolve().parents[1] / "db" / "migrations"
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        print("No migrations found", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(database_url)
    try:
        for path in files:
            sql = path.read_text(encoding="utf-8")
            if not sql.strip():
                continue
            await conn.execute(sql)
            print(f"applied {path.name}")
    finally:
        await conn.close()

    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
