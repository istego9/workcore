from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg

from apps.orchestrator.runtime.models import Event as RuntimeEvent
from apps.orchestrator.runtime.models import Run


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


_STATUS_BY_EVENT = {
    "run_started": "RUNNING",
    "run_waiting_for_input": "WAITING_FOR_INPUT",
    "run_completed": "COMPLETED",
    "run_failed": "FAILED",
    "run_cancelled": "CANCELLED",
    "node_started": "IN_PROGRESS",
    "node_completed": "RESOLVED",
    "node_failed": "ERROR",
    "node_retry": "RETRYING",
    "message_generated": "RUNNING",
    "snapshot": "SNAPSHOT",
    "stream_end": "STREAM_END",
}


@dataclass
class RunLedgerEntry:
    ledger_id: str
    tenant_id: str
    run_id: str
    workflow_id: str
    version_id: str
    step_id: Optional[str]
    capability_id: Optional[str]
    capability_version: Optional[str]
    status: str
    event_type: str
    decision: Optional[Dict[str, Any]]
    artifacts: List[str]
    payload: Dict[str, Any]
    timestamp: datetime = field(default_factory=_now)


class InMemoryRunLedgerStore:
    def __init__(self, tenant_id: str = "local") -> None:
        self.tenant_id = tenant_id
        self._items: Dict[tuple[str, str], List[RunLedgerEntry]] = {}

    async def append_entries(self, entries: List[RunLedgerEntry]) -> None:
        for entry in entries:
            key = (entry.tenant_id, entry.run_id)
            self._items.setdefault(key, []).append(entry)

    async def list_run(self, run_id: str, tenant_id: Optional[str] = None, limit: int = 200) -> List[RunLedgerEntry]:
        tenant = tenant_id or self.tenant_id
        items = list(self._items.get((tenant, run_id), []))
        items.sort(key=lambda item: item.timestamp)
        return items[:limit]

    async def close(self) -> None:
        return None


@dataclass
class PostgresRunLedgerStore:
    pool: asyncpg.Pool
    tenant_id: str = "local"

    async def append_entries(self, entries: List[RunLedgerEntry]) -> None:
        if not entries:
            return
        rows = [
            (
                entry.ledger_id,
                entry.tenant_id,
                entry.run_id,
                entry.workflow_id,
                entry.version_id,
                entry.step_id,
                entry.capability_id,
                entry.capability_version,
                entry.status,
                entry.event_type,
                _jsonb(entry.decision) if entry.decision is not None else None,
                _jsonb(entry.artifacts),
                _jsonb(entry.payload),
                entry.timestamp,
            )
            for entry in entries
        ]
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                insert into run_ledger (
                  id, tenant_id, run_id, workflow_id, version_id, step_id,
                  capability_id, capability_version, status, event_type, decision,
                  artifacts, payload, created_at
                )
                values (
                  $1, $2, $3, $4, $5, $6,
                  $7, $8, $9, $10, $11::jsonb,
                  $12::jsonb, $13::jsonb, $14
                )
                on conflict (id) do nothing
                """,
                rows,
            )

    async def list_run(self, run_id: str, tenant_id: Optional[str] = None, limit: int = 200) -> List[RunLedgerEntry]:
        tenant = tenant_id or self.tenant_id
        rows = await self.pool.fetch(
            """
            select
              id, tenant_id, run_id, workflow_id, version_id, step_id,
              capability_id, capability_version, status, event_type, decision,
              artifacts, payload, created_at
            from run_ledger
            where tenant_id = $1 and run_id = $2
            order by created_at asc
            limit $3
            """,
            tenant,
            run_id,
            limit,
        )
        return [
            RunLedgerEntry(
                ledger_id=row["id"],
                tenant_id=row["tenant_id"],
                run_id=row["run_id"],
                workflow_id=row["workflow_id"],
                version_id=row["version_id"],
                step_id=row["step_id"],
                capability_id=row["capability_id"],
                capability_version=row["capability_version"],
                status=row["status"],
                event_type=row["event_type"],
                decision=_parse_json(row["decision"]) if row["decision"] is not None else None,
                artifacts=[str(item) for item in (_parse_json(row["artifacts"]) or []) if isinstance(item, str)],
                payload=_parse_json(row["payload"]) if isinstance(_parse_json(row["payload"]), dict) else {},
                timestamp=row["created_at"],
            )
            for row in rows
        ]

    async def close(self) -> None:
        return None


async def create_run_ledger_store(
    workflow_store: Any | None,
    tenant_id: str = "local",
) -> InMemoryRunLedgerStore | PostgresRunLedgerStore:
    pool = getattr(workflow_store, "pool", None)
    if isinstance(pool, asyncpg.Pool):
        return PostgresRunLedgerStore(pool=pool, tenant_id=tenant_id)
    return InMemoryRunLedgerStore(tenant_id=tenant_id)


def _artifact_refs(payload: Any) -> List[str]:
    refs: List[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "artifact_ref" and isinstance(item, str) and item:
                    refs.append(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    seen: set[str] = set()
    unique: List[str] = []
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        unique.append(ref)
    return unique


def _as_text(value: Any) -> Optional[str]:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _error_from_payload(payload: Dict[str, Any]) -> Optional[str]:
    for key in ("error", "message", "reason"):
        value = payload.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
        if isinstance(value, dict):
            nested = value.get("message")
            if isinstance(nested, str):
                normalized = nested.strip()
                if normalized:
                    return normalized
    return None


def _fallback_failed_node(run: Run) -> Optional[Any]:
    node_runs = list((run.node_runs or {}).values())
    for node_run in reversed(node_runs):
        if node_run.last_error:
            return node_run
    for node_run in reversed(node_runs):
        if node_run.status == "ERROR":
            return node_run
    return None


def _enrich_run_failed_payload(
    run: Run,
    payload: Dict[str, Any],
    event_node_id: Optional[str],
) -> tuple[Dict[str, Any], Optional[str]]:
    enriched = dict(payload or {})
    metadata = run.metadata if isinstance(run.metadata, dict) else {}

    resolved_node_id = _as_text(event_node_id) or _as_text(enriched.get("node_id"))
    resolved_error = _error_from_payload(enriched)
    resolved_trace = _as_text(enriched.get("trace_id"))

    fallback_node = _fallback_failed_node(run)
    if fallback_node is not None:
        if resolved_node_id is None:
            resolved_node_id = _as_text(getattr(fallback_node, "node_id", None))
        if resolved_error is None:
            resolved_error = _as_text(getattr(fallback_node, "last_error", None))
        if resolved_trace is None:
            resolved_trace = _as_text(getattr(fallback_node, "trace_id", None))

    if resolved_node_id is not None:
        enriched["node_id"] = resolved_node_id
    if resolved_error is not None:
        enriched["error"] = resolved_error
    if resolved_trace is not None:
        enriched["trace_id"] = resolved_trace

    correlation_id = _as_text(metadata.get("correlation_id"))
    if correlation_id is not None and _as_text(enriched.get("correlation_id")) is None:
        enriched["correlation_id"] = correlation_id

    return enriched, resolved_node_id


def runtime_events_to_ledger_entries(run: Run, events: List[RuntimeEvent]) -> List[RunLedgerEntry]:
    metadata = run.metadata or {}
    tenant = str(metadata.get("tenant_id") or "local")
    bindings = metadata.get("capability_bindings")
    if not isinstance(bindings, dict):
        bindings = {}

    entries: List[RunLedgerEntry] = []
    for event in events:
        payload_raw = event.payload if isinstance(event.payload, dict) else {}
        payload = dict(payload_raw or {})
        step_id = event.node_id
        if event.type == "run_failed":
            payload, resolved_node_id = _enrich_run_failed_payload(run, payload, event.node_id)
            if step_id is None:
                step_id = resolved_node_id
        node_binding = bindings.get(event.node_id or "") if isinstance(bindings, dict) else None
        if not isinstance(node_binding, dict):
            node_binding = {}
        decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else None
        status = _STATUS_BY_EVENT.get(event.type, run.status)
        entries.append(
            RunLedgerEntry(
                ledger_id=_new_id("led"),
                tenant_id=tenant,
                run_id=run.id,
                workflow_id=run.workflow_id,
                version_id=run.version_id,
                step_id=step_id,
                capability_id=node_binding.get("capability_id") if isinstance(node_binding.get("capability_id"), str) else None,
                capability_version=node_binding.get("capability_version")
                if isinstance(node_binding.get("capability_version"), str)
                else None,
                status=str(status),
                event_type=event.type,
                decision=decision,
                artifacts=_artifact_refs(payload),
                payload=payload,
            )
        )
    return entries
