from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _jsonb(value: Any) -> str:
    return json.dumps(value)


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


class CapabilityConflictError(RuntimeError):
    pass


@dataclass
class CapabilityRecord:
    capability_id: str
    version: str
    node_type: str
    contract: Dict[str, Any]
    tenant_id: str
    created_at: datetime = field(default_factory=_now)


class InMemoryCapabilityStore:
    def __init__(self, tenant_id: str = "local") -> None:
        self.tenant_id = tenant_id
        self._items: Dict[tuple[str, str, str], CapabilityRecord] = {}

    async def create(
        self,
        capability_id: str,
        version: str,
        node_type: str,
        contract: Dict[str, Any],
        tenant_id: Optional[str] = None,
    ) -> CapabilityRecord:
        tenant = tenant_id or self.tenant_id
        key = (tenant, capability_id, version)
        if key in self._items:
            raise CapabilityConflictError("capability version already exists")
        record = CapabilityRecord(
            capability_id=capability_id,
            version=version,
            node_type=node_type,
            contract=dict(contract or {}),
            tenant_id=tenant,
        )
        self._items[key] = record
        return record

    async def get(self, capability_id: str, version: str, tenant_id: Optional[str] = None) -> Optional[CapabilityRecord]:
        tenant = tenant_id or self.tenant_id
        return self._items.get((tenant, capability_id, version))

    async def list_capabilities(
        self,
        tenant_id: Optional[str] = None,
        capability_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[CapabilityRecord]:
        tenant = tenant_id or self.tenant_id
        items = [record for (item_tenant, _, _), record in self._items.items() if item_tenant == tenant]
        if capability_id:
            items = [record for record in items if record.capability_id == capability_id]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[:limit]

    async def list_versions(
        self,
        capability_id: str,
        tenant_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[CapabilityRecord]:
        return await self.list_capabilities(tenant_id=tenant_id, capability_id=capability_id, limit=limit)

    async def close(self) -> None:
        return None


@dataclass
class PostgresCapabilityStore:
    pool: asyncpg.Pool
    tenant_id: str = "local"

    async def create(
        self,
        capability_id: str,
        version: str,
        node_type: str,
        contract: Dict[str, Any],
        tenant_id: Optional[str] = None,
    ) -> CapabilityRecord:
        tenant = tenant_id or self.tenant_id
        row = await self.pool.fetchrow(
            """
            insert into capabilities (id, tenant_id, capability_id, version, node_type, contract, created_at)
            values ($1, $2, $3, $4, $5, $6::jsonb, now())
            on conflict (tenant_id, capability_id, version) do nothing
            returning capability_id, version, node_type, contract, tenant_id, created_at
            """,
            _new_id("cap"),
            tenant,
            capability_id,
            version,
            node_type,
            _jsonb(contract or {}),
        )
        if not row:
            raise CapabilityConflictError("capability version already exists")
        return CapabilityRecord(
            capability_id=row["capability_id"],
            version=row["version"],
            node_type=row["node_type"],
            contract=_parse_json(row["contract"]) or {},
            tenant_id=row["tenant_id"],
            created_at=row["created_at"],
        )

    async def get(self, capability_id: str, version: str, tenant_id: Optional[str] = None) -> Optional[CapabilityRecord]:
        tenant = tenant_id or self.tenant_id
        row = await self.pool.fetchrow(
            """
            select capability_id, version, node_type, contract, tenant_id, created_at
            from capabilities
            where tenant_id = $1 and capability_id = $2 and version = $3
            """,
            tenant,
            capability_id,
            version,
        )
        if not row:
            return None
        return CapabilityRecord(
            capability_id=row["capability_id"],
            version=row["version"],
            node_type=row["node_type"],
            contract=_parse_json(row["contract"]) or {},
            tenant_id=row["tenant_id"],
            created_at=row["created_at"],
        )

    async def list_capabilities(
        self,
        tenant_id: Optional[str] = None,
        capability_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[CapabilityRecord]:
        tenant = tenant_id or self.tenant_id
        rows = await self.pool.fetch(
            """
            select capability_id, version, node_type, contract, tenant_id, created_at
            from capabilities
            where tenant_id = $1
              and ($2::text is null or capability_id = $2)
            order by created_at desc
            limit $3
            """,
            tenant,
            capability_id,
            limit,
        )
        return [
            CapabilityRecord(
                capability_id=row["capability_id"],
                version=row["version"],
                node_type=row["node_type"],
                contract=_parse_json(row["contract"]) or {},
                tenant_id=row["tenant_id"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def list_versions(
        self,
        capability_id: str,
        tenant_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[CapabilityRecord]:
        return await self.list_capabilities(tenant_id=tenant_id, capability_id=capability_id, limit=limit)

    async def close(self) -> None:
        return None


async def create_capability_store(
    workflow_store: Any | None,
    tenant_id: str = "local",
) -> InMemoryCapabilityStore | PostgresCapabilityStore:
    pool = getattr(workflow_store, "pool", None)
    if isinstance(pool, asyncpg.Pool):
        return PostgresCapabilityStore(pool=pool, tenant_id=tenant_id)
    return InMemoryCapabilityStore(tenant_id=tenant_id)
