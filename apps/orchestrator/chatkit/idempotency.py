from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Optional
import json

import asyncpg


@dataclass
class IdempotencyStore:
    pool: asyncpg.Pool
    ttl_seconds: int = 300
    tenant_id: str = "local"

    async def start(self, key: str, scope: str) -> bool:
        now = time.time()
        expires_at = now + self.ttl_seconds
        request_hash = hashlib.sha256(f"{scope}:{key}".encode()).hexdigest()
        try:
            await self.pool.execute(
                """
                insert into idempotency_keys (
                    id, tenant_id, idempotency_key, scope, request_hash,
                    status, expires_at, created_at
                )
                values ($1, $2, $3, $4, $5, $6, to_timestamp($7), now())
                """,
                f"idem_{uuid.uuid4().hex[:10]}",
                self.tenant_id,
                key,
                scope,
                request_hash,
                "IN_PROGRESS",
                expires_at,
            )
            return True
        except asyncpg.UniqueViolationError:
            return False

    async def complete(self, key: str, scope: str, response_body: Optional[dict] = None) -> None:
        payload = json.dumps(response_body) if response_body is not None else None
        await self.pool.execute(
            """
            update idempotency_keys
            set status = $1,
                response_body = $2::jsonb,
                expires_at = to_timestamp($3)
            where tenant_id = $4 and idempotency_key = $5 and scope = $6
            """,
            "COMPLETED",
            payload,
            time.time() + self.ttl_seconds,
            self.tenant_id,
            key,
            scope,
        )

    async def fail(self, key: str, scope: str, response_body: Optional[dict] = None) -> None:
        payload = json.dumps(response_body) if response_body is not None else None
        await self.pool.execute(
            """
            update idempotency_keys
            set status = $1,
                response_body = $2::jsonb,
                expires_at = to_timestamp($3)
            where tenant_id = $4 and idempotency_key = $5 and scope = $6
            """,
            "FAILED",
            payload,
            time.time() + self.ttl_seconds,
            self.tenant_id,
            key,
            scope,
        )
