from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

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


class HandoffConflictError(RuntimeError):
    pass


@dataclass
class HandoffPackageRecord:
    handoff_id: str
    tenant_id: str
    workflow_id: str
    version_id: Optional[str]
    context: Dict[str, Any]
    constraints: Dict[str, Any]
    expected_result: Dict[str, Any]
    acceptance_checks: list[Dict[str, Any]]
    replay_mode: str
    idempotency_key: Optional[str]
    run_id: Optional[str]
    status: str
    metadata: Dict[str, Any]
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


class InMemoryHandoffStore:
    def __init__(self, tenant_id: str = "local") -> None:
        self.tenant_id = tenant_id
        self._items: Dict[tuple[str, str], HandoffPackageRecord] = {}
        self._idem: Dict[tuple[str, str], str] = {}

    async def create(
        self,
        workflow_id: str,
        version_id: Optional[str],
        context: Dict[str, Any],
        constraints: Dict[str, Any],
        expected_result: Dict[str, Any],
        acceptance_checks: list[Dict[str, Any]],
        replay_mode: str,
        metadata: Dict[str, Any],
        tenant_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> HandoffPackageRecord:
        tenant = tenant_id or self.tenant_id
        if idempotency_key:
            idem_key = (tenant, idempotency_key)
            existing_id = self._idem.get(idem_key)
            if existing_id:
                existing = self._items.get((tenant, existing_id))
                if existing:
                    return existing

        handoff_id = _new_id("hof")
        record = HandoffPackageRecord(
            handoff_id=handoff_id,
            tenant_id=tenant,
            workflow_id=workflow_id,
            version_id=version_id,
            context=dict(context or {}),
            constraints=dict(constraints or {}),
            expected_result=dict(expected_result or {}),
            acceptance_checks=list(acceptance_checks or []),
            replay_mode=replay_mode or "none",
            idempotency_key=idempotency_key,
            run_id=None,
            status="RECEIVED",
            metadata=dict(metadata or {}),
        )
        self._items[(tenant, handoff_id)] = record
        if idempotency_key:
            self._idem[(tenant, idempotency_key)] = handoff_id
        return record

    async def get(self, handoff_id: str, tenant_id: Optional[str] = None) -> Optional[HandoffPackageRecord]:
        tenant = tenant_id or self.tenant_id
        return self._items.get((tenant, handoff_id))

    async def update_status(
        self,
        handoff_id: str,
        status: str,
        run_id: Optional[str],
        tenant_id: Optional[str] = None,
    ) -> Optional[HandoffPackageRecord]:
        tenant = tenant_id or self.tenant_id
        record = self._items.get((tenant, handoff_id))
        if not record:
            return None
        record.status = status
        record.run_id = run_id
        record.updated_at = _now()
        return record

    async def close(self) -> None:
        return None


@dataclass
class PostgresHandoffStore:
    pool: asyncpg.Pool
    tenant_id: str = "local"

    async def create(
        self,
        workflow_id: str,
        version_id: Optional[str],
        context: Dict[str, Any],
        constraints: Dict[str, Any],
        expected_result: Dict[str, Any],
        acceptance_checks: list[Dict[str, Any]],
        replay_mode: str,
        metadata: Dict[str, Any],
        tenant_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> HandoffPackageRecord:
        tenant = tenant_id or self.tenant_id
        if idempotency_key:
            existing = await self.pool.fetchrow(
                """
                select
                  id, tenant_id, workflow_id, version_id, context, constraints, expected_result,
                  acceptance_checks, replay_mode, idempotency_key, run_id, status, metadata,
                  created_at, updated_at
                from workflow_handoffs
                where tenant_id = $1 and idempotency_key = $2
                """,
                tenant,
                idempotency_key,
            )
            if existing:
                return _handoff_from_row(existing)

        handoff_id = _new_id("hof")
        row = await self.pool.fetchrow(
            """
            insert into workflow_handoffs (
              id, tenant_id, workflow_id, version_id, context, constraints, expected_result,
              acceptance_checks, replay_mode, idempotency_key, run_id, status, metadata,
              created_at, updated_at
            )
            values (
              $1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb,
              $8::jsonb, $9, $10, null, 'RECEIVED', $11::jsonb,
              now(), now()
            )
            returning
              id, tenant_id, workflow_id, version_id, context, constraints, expected_result,
              acceptance_checks, replay_mode, idempotency_key, run_id, status, metadata,
              created_at, updated_at
            """,
            handoff_id,
            tenant,
            workflow_id,
            version_id,
            _jsonb(context or {}),
            _jsonb(constraints or {}),
            _jsonb(expected_result or {}),
            _jsonb(acceptance_checks or []),
            replay_mode or "none",
            idempotency_key,
            _jsonb(metadata or {}),
        )
        if not row:
            raise HandoffConflictError("failed to create handoff package")
        return _handoff_from_row(row)

    async def get(self, handoff_id: str, tenant_id: Optional[str] = None) -> Optional[HandoffPackageRecord]:
        tenant = tenant_id or self.tenant_id
        row = await self.pool.fetchrow(
            """
            select
              id, tenant_id, workflow_id, version_id, context, constraints, expected_result,
              acceptance_checks, replay_mode, idempotency_key, run_id, status, metadata,
              created_at, updated_at
            from workflow_handoffs
            where tenant_id = $1 and id = $2
            """,
            tenant,
            handoff_id,
        )
        if not row:
            return None
        return _handoff_from_row(row)

    async def update_status(
        self,
        handoff_id: str,
        status: str,
        run_id: Optional[str],
        tenant_id: Optional[str] = None,
    ) -> Optional[HandoffPackageRecord]:
        tenant = tenant_id or self.tenant_id
        row = await self.pool.fetchrow(
            """
            update workflow_handoffs
            set status = $1,
                run_id = $2,
                updated_at = now()
            where tenant_id = $3 and id = $4
            returning
              id, tenant_id, workflow_id, version_id, context, constraints, expected_result,
              acceptance_checks, replay_mode, idempotency_key, run_id, status, metadata,
              created_at, updated_at
            """,
            status,
            run_id,
            tenant,
            handoff_id,
        )
        if not row:
            return None
        return _handoff_from_row(row)

    async def close(self) -> None:
        return None


def _handoff_from_row(row: Any) -> HandoffPackageRecord:
    checks = _parse_json(row["acceptance_checks"])
    if not isinstance(checks, list):
        checks = []
    normalized_checks: list[Dict[str, Any]] = [item for item in checks if isinstance(item, dict)]
    return HandoffPackageRecord(
        handoff_id=row["id"],
        tenant_id=row["tenant_id"],
        workflow_id=row["workflow_id"],
        version_id=row["version_id"],
        context=_parse_json(row["context"]) if isinstance(_parse_json(row["context"]), dict) else {},
        constraints=_parse_json(row["constraints"]) if isinstance(_parse_json(row["constraints"]), dict) else {},
        expected_result=_parse_json(row["expected_result"])
        if isinstance(_parse_json(row["expected_result"]), dict)
        else {},
        acceptance_checks=normalized_checks,
        replay_mode=row["replay_mode"],
        idempotency_key=row["idempotency_key"],
        run_id=row["run_id"],
        status=row["status"],
        metadata=_parse_json(row["metadata"]) if isinstance(_parse_json(row["metadata"]), dict) else {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create_handoff_store(
    workflow_store: Any | None,
    tenant_id: str = "local",
) -> InMemoryHandoffStore | PostgresHandoffStore:
    pool = getattr(workflow_store, "pool", None)
    if isinstance(pool, asyncpg.Pool):
        return PostgresHandoffStore(pool=pool, tenant_id=tenant_id)
    return InMemoryHandoffStore(tenant_id=tenant_id)
