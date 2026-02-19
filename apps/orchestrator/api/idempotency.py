from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol

import asyncpg


@dataclass
class IdempotencyResponse:
    status_code: int
    body: Any


class IdempotencyStore(Protocol):
    async def get(self, key: str, scope: str, tenant_id: Optional[str] = None) -> Optional[IdempotencyResponse]:
        ...

    async def set(
        self,
        key: str,
        scope: str,
        status_code: int,
        body: Any,
        tenant_id: Optional[str] = None,
    ) -> None:
        ...

    async def close(self) -> None:
        ...


def _sanitize_for_jsonb(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_sanitize_for_jsonb(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_for_jsonb(item) for item in value]
    if isinstance(value, dict):
        sanitized: Dict[Any, Any] = {}
        for key, item in value.items():
            sanitized_key = key.replace("\x00", "") if isinstance(key, str) else key
            sanitized[sanitized_key] = _sanitize_for_jsonb(item)
        return sanitized
    return value


class InMemoryIdempotencyStore:
    def __init__(self, ttl_s: int = 300) -> None:
        self.ttl_s = ttl_s
        self._entries: Dict[str, tuple[float, IdempotencyResponse]] = {}

    @staticmethod
    def _key(tenant_id: str, scope: str, key: str) -> str:
        return f"{tenant_id}:{scope}:{key}"

    async def get(self, key: str, scope: str, tenant_id: Optional[str] = None) -> Optional[IdempotencyResponse]:
        tenant = tenant_id or "local"
        record = self._entries.get(self._key(tenant, scope, key))
        if not record:
            return None
        expires_at, response = record
        if expires_at <= time.time():
            self._entries.pop(self._key(tenant, scope, key), None)
            return None
        return response

    async def set(
        self,
        key: str,
        scope: str,
        status_code: int,
        body: Any,
        tenant_id: Optional[str] = None,
    ) -> None:
        tenant = tenant_id or "local"
        self._entries[self._key(tenant, scope, key)] = (
            time.time() + self.ttl_s,
            IdempotencyResponse(status_code=status_code, body=body),
        )

    async def close(self) -> None:
        return None


class PostgresIdempotencyStore:
    def __init__(self, pool: asyncpg.Pool, tenant_id: str = "local", ttl_s: int = 300) -> None:
        self.pool = pool
        self.tenant_id = tenant_id
        self.ttl_s = ttl_s

    async def get(self, key: str, scope: str, tenant_id: Optional[str] = None) -> Optional[IdempotencyResponse]:
        tenant = tenant_id or self.tenant_id
        row = await self.pool.fetchrow(
            """
            select status, response_body, expires_at
            from idempotency_keys
            where tenant_id = $1 and idempotency_key = $2 and scope = $3
            """,
            tenant,
            key,
            scope,
        )
        if not row:
            return None

        expires_at = row["expires_at"]
        if isinstance(expires_at, datetime):
            if expires_at <= datetime.now(timezone.utc):
                await self.pool.execute(
                    """
                    delete from idempotency_keys
                    where tenant_id = $1 and idempotency_key = $2 and scope = $3
                    """,
                    tenant,
                    key,
                    scope,
                )
                return None

        if row["status"] != "COMPLETED":
            return None

        payload = row["response_body"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = None
        if not isinstance(payload, dict):
            return None

        status_code = payload.get("status_code")
        body = payload.get("body")
        if not isinstance(status_code, int):
            return None
        return IdempotencyResponse(status_code=status_code, body=body)

    async def set(
        self,
        key: str,
        scope: str,
        status_code: int,
        body: Any,
        tenant_id: Optional[str] = None,
    ) -> None:
        tenant = tenant_id or self.tenant_id
        now_ts = time.time()
        expires_at = now_ts + self.ttl_s
        request_hash = hashlib.sha256(f"{scope}:{key}".encode("utf-8")).hexdigest()
        payload = json.dumps(
            _sanitize_for_jsonb({"status_code": status_code, "body": body}),
            ensure_ascii=False,
        )
        await self.pool.execute(
            """
            insert into idempotency_keys (
                id, tenant_id, idempotency_key, scope, request_hash,
                response_body, status, expires_at, created_at
            )
            values ($1, $2, $3, $4, $5, $6::jsonb, $7, to_timestamp($8), now())
            on conflict (tenant_id, idempotency_key, scope) do update
            set request_hash = excluded.request_hash,
                response_body = excluded.response_body,
                status = excluded.status,
                expires_at = excluded.expires_at
            """,
            f"idem_{uuid.uuid4().hex[:10]}",
            tenant,
            key,
            scope,
            request_hash,
            payload,
            "COMPLETED",
            expires_at,
        )

    async def close(self) -> None:
        return None


async def create_idempotency_store(
    workflow_store: Any | None,
    ttl_s: int = 300,
) -> IdempotencyStore:
    pool = getattr(workflow_store, "pool", None)
    if isinstance(pool, asyncpg.Pool):
        return PostgresIdempotencyStore(pool=pool, ttl_s=ttl_s)
    return InMemoryIdempotencyStore(ttl_s=ttl_s)
