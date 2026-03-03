from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

import asyncpg

from .events import EventEnvelope


class EventStore(Protocol):
    async def append(self, event: EventEnvelope) -> EventEnvelope:
        ...

    async def list_events(self, run_id: str, after_id: Optional[str] = None) -> List[EventEnvelope]:
        ...

    async def get_snapshot(self, run_id: str) -> Optional[EventEnvelope]:
        ...

    async def set_snapshot(self, run_id: str, snapshot: EventEnvelope) -> None:
        ...

    async def last_event(self, run_id: str) -> Optional[EventEnvelope]:
        ...

    async def last_sequence(self, run_id: str) -> int:
        ...


@dataclass
class InMemoryEventStore:
    events: Dict[str, List[EventEnvelope]]
    snapshots: Dict[str, EventEnvelope]
    sequences: Dict[str, int]

    def __init__(self) -> None:
        self.events = {}
        self.snapshots = {}
        self.sequences = {}

    async def append(self, event: EventEnvelope) -> EventEnvelope:
        next_seq = self.sequences.get(event.run_id, 0) + 1
        self.sequences[event.run_id] = next_seq
        event.sequence = next_seq
        self.events.setdefault(event.run_id, []).append(event)
        return event

    async def list_events(self, run_id: str, after_id: Optional[str] = None) -> List[EventEnvelope]:
        items = list(self.events.get(run_id, []))
        if not after_id:
            return items
        for idx, event in enumerate(items):
            if event.id == after_id:
                return items[idx + 1 :]
        return items

    async def get_snapshot(self, run_id: str) -> Optional[EventEnvelope]:
        return self.snapshots.get(run_id)

    async def set_snapshot(self, run_id: str, snapshot: EventEnvelope) -> None:
        if snapshot.sequence <= 0:
            snapshot.sequence = self.sequences.get(run_id, 0)
        self.snapshots[run_id] = snapshot

    async def last_event(self, run_id: str) -> Optional[EventEnvelope]:
        items = self.events.get(run_id, [])
        if not items:
            return None
        return items[-1]

    async def last_sequence(self, run_id: str) -> int:
        return self.sequences.get(run_id, 0)


def _jsonb(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _parse_payload(value: Any) -> Dict[str, Any]:
    parsed = _parse_json(value)
    if isinstance(parsed, dict):
        return parsed
    return {}


def _created_timestamp(value: Any) -> float:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    return datetime.now(timezone.utc).timestamp()


@dataclass
class PostgresEventStore:
    pool: asyncpg.Pool
    default_tenant_id: str = "local"

    async def append(self, event: EventEnvelope) -> EventEnvelope:
        tenant_id = event.tenant_id or self.default_tenant_id
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("select pg_advisory_xact_lock(hashtext($1))", event.run_id)
                row = await conn.fetchrow(
                    """
                    select coalesce(max(sequence), 0) as seq
                    from events
                    where run_id = $1 and sequence is not null and type <> 'snapshot'
                    """,
                    event.run_id,
                )
                current_seq = int(row["seq"]) if row and row["seq"] is not None else 0
                next_seq = current_seq + 1
                await conn.execute(
                    """
                    insert into events (
                        id, run_id, workflow_id, version_id, node_id, tenant_id,
                        type, payload, correlation_id, sequence, created_at
                    )
                    values ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10, to_timestamp($11))
                    """,
                    event.id,
                    event.run_id,
                    event.workflow_id,
                    event.version_id,
                    event.node_id,
                    tenant_id,
                    event.type,
                    _jsonb(event.payload or {}),
                    event.correlation_id,
                    next_seq,
                    float(event.timestamp),
                )
        event.sequence = next_seq
        event.tenant_id = tenant_id
        return event

    async def list_events(self, run_id: str, after_id: Optional[str] = None) -> List[EventEnvelope]:
        after_sequence: Optional[int] = None
        if after_id:
            marker = await self.pool.fetchrow(
                """
                select id, type, sequence, payload
                from events
                where run_id = $1 and id = $2
                limit 1
                """,
                run_id,
                after_id,
            )
            if marker:
                marker_seq = marker["sequence"]
                if isinstance(marker_seq, int):
                    after_sequence = marker_seq
                else:
                    payload = _parse_payload(marker["payload"])
                    payload_last_seq = payload.get("last_sequence")
                    if isinstance(payload_last_seq, int):
                        after_sequence = payload_last_seq
                    else:
                        payload_last_id = payload.get("last_event_id")
                        if isinstance(payload_last_id, str) and payload_last_id:
                            row = await self.pool.fetchrow(
                                """
                                select sequence
                                from events
                                where run_id = $1 and id = $2
                                limit 1
                                """,
                                run_id,
                                payload_last_id,
                            )
                            if row and isinstance(row["sequence"], int):
                                after_sequence = int(row["sequence"])

        if after_sequence is None:
            rows = await self.pool.fetch(
                """
                select id, run_id, workflow_id, version_id, node_id, tenant_id, type, payload,
                       correlation_id, sequence, created_at
                from events
                where run_id = $1 and type <> 'snapshot'
                order by sequence asc, created_at asc
                """,
                run_id,
            )
        else:
            rows = await self.pool.fetch(
                """
                select id, run_id, workflow_id, version_id, node_id, tenant_id, type, payload,
                       correlation_id, sequence, created_at
                from events
                where run_id = $1 and type <> 'snapshot' and sequence > $2
                order by sequence asc, created_at asc
                """,
                run_id,
                after_sequence,
            )
        return [self._to_envelope(row) for row in rows]

    async def get_snapshot(self, run_id: str) -> Optional[EventEnvelope]:
        row = await self.pool.fetchrow(
            """
            select id, run_id, workflow_id, version_id, node_id, tenant_id, type, payload,
                   correlation_id, sequence, created_at
            from events
            where run_id = $1 and type = 'snapshot'
            order by created_at desc
            limit 1
            """,
            run_id,
        )
        if not row:
            return None
        return self._to_envelope(row)

    async def set_snapshot(self, run_id: str, snapshot: EventEnvelope) -> None:
        tenant_id = snapshot.tenant_id or self.default_tenant_id
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("delete from events where run_id = $1 and type = 'snapshot'", run_id)
                await conn.execute(
                    """
                    insert into events (
                        id, run_id, workflow_id, version_id, node_id, tenant_id,
                        type, payload, correlation_id, sequence, created_at
                    )
                    values ($1, $2, $3, $4, $5, $6, 'snapshot', $7::jsonb, $8, null, to_timestamp($9))
                    """,
                    snapshot.id,
                    run_id,
                    snapshot.workflow_id,
                    snapshot.version_id,
                    snapshot.node_id,
                    tenant_id,
                    _jsonb(snapshot.payload or {}),
                    snapshot.correlation_id,
                    float(snapshot.timestamp),
                )

    async def last_event(self, run_id: str) -> Optional[EventEnvelope]:
        row = await self.pool.fetchrow(
            """
            select id, run_id, workflow_id, version_id, node_id, tenant_id, type, payload,
                   correlation_id, sequence, created_at
            from events
            where run_id = $1 and type <> 'snapshot'
            order by sequence desc, created_at desc
            limit 1
            """,
            run_id,
        )
        if not row:
            return None
        return self._to_envelope(row)

    async def last_sequence(self, run_id: str) -> int:
        row = await self.pool.fetchrow(
            """
            select coalesce(max(sequence), 0) as seq
            from events
            where run_id = $1 and sequence is not null and type <> 'snapshot'
            """,
            run_id,
        )
        if not row:
            return 0
        seq = row["seq"]
        return int(seq) if isinstance(seq, int) else 0

    @staticmethod
    def _to_envelope(row: Any) -> EventEnvelope:
        payload = _parse_payload(row["payload"])
        sequence = row["sequence"]
        resolved_sequence = int(sequence) if isinstance(sequence, int) else 0
        if resolved_sequence <= 0:
            payload_seq = payload.get("last_sequence")
            if isinstance(payload_seq, int):
                resolved_sequence = payload_seq
        return EventEnvelope(
            id=str(row["id"]),
            type=str(row["type"]),
            run_id=str(row["run_id"]),
            workflow_id=str(row["workflow_id"]),
            version_id=str(row["version_id"]),
            node_id=row["node_id"],
            payload=payload,
            timestamp=_created_timestamp(row["created_at"]),
            sequence=resolved_sequence,
            correlation_id=row["correlation_id"],
            tenant_id=row["tenant_id"],
        )


def create_event_store(
    backend: str,
    pool: Optional[asyncpg.Pool] = None,
    tenant_id: str = "local",
) -> EventStore:
    normalized = (backend or "").strip().lower()
    if normalized == "postgres":
        if not isinstance(pool, asyncpg.Pool):
            raise RuntimeError("STREAMING_STORE_BACKEND=postgres requires asyncpg pool")
        return PostgresEventStore(pool=pool, default_tenant_id=tenant_id)
    if normalized and normalized != "memory":
        raise RuntimeError(f"unsupported STREAMING_STORE_BACKEND: {backend}")
    return InMemoryEventStore()


def create_event_store_from_env(
    pool: Optional[asyncpg.Pool] = None,
    tenant_id: str = "local",
) -> EventStore:
    backend = os.getenv("STREAMING_STORE_BACKEND", "memory")
    return create_event_store(backend=backend, pool=pool, tenant_id=tenant_id)
