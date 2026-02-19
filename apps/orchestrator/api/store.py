from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import asyncpg

from apps.orchestrator.runtime.models import Interrupt, NodeRun
from apps.orchestrator.runtime.models import Run
from apps.orchestrator.runtime.projection import project_run_payload_for_transport


@dataclass
class InMemoryRunStore:
    runs: Dict[str, Run] = field(default_factory=dict)
    tenant_id: str = "local"

    @staticmethod
    def _run_tenant(run: Run, fallback: str = "local") -> str:
        metadata = run.metadata or {}
        tenant = metadata.get("tenant_id")
        if isinstance(tenant, str) and tenant:
            return tenant
        return fallback

    def save(self, run: Run, tenant_id: Optional[str] = None) -> None:
        tenant = tenant_id or self._run_tenant(run, self.tenant_id)
        run.metadata = dict(run.metadata or {})
        run.metadata["tenant_id"] = tenant
        _apply_run_timestamps(run)
        projected_state, projected_outputs = project_run_payload_for_transport(run.state, run.outputs, run.metadata)
        persisted_run = Run(
            id=run.id,
            workflow_id=run.workflow_id,
            version_id=run.version_id,
            status=run.status,
            inputs=run.inputs,
            state=projected_state if isinstance(projected_state, dict) else {},
            mode=run.mode,
            outputs=projected_outputs if isinstance(projected_outputs, dict) else None,
            node_runs=run.node_runs,
            node_outputs=run.node_outputs,
            interrupts=run.interrupts,
            branch_selection=run.branch_selection,
            loop_state=run.loop_state,
            skipped_nodes=run.skipped_nodes,
            metadata=run.metadata,
        )
        self.runs[run.id] = persisted_run

    def get(self, run_id: str, tenant_id: Optional[str] = None) -> Optional[Run]:
        run = self.runs.get(run_id)
        if not run:
            return None
        tenant = tenant_id or self.tenant_id
        if self._run_tenant(run, self.tenant_id) != tenant:
            return None
        return run

    def list(
        self,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> List[Run]:
        tenant = tenant_id or self.tenant_id
        items = list(self.runs.values())
        items = [run for run in items if self._run_tenant(run, self.tenant_id) == tenant]
        if workflow_id:
            items = [run for run in items if run.workflow_id == workflow_id]
        if status:
            items = [run for run in items if run.status == status]
        return items

    async def close(self) -> None:
        return None


def _sanitize_for_jsonb(value: Any) -> Any:
    # PostgreSQL jsonb rejects \u0000; strip NUL bytes from nested strings before serialization.
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


def _jsonb(value: Any) -> str:
    return json.dumps(_sanitize_for_jsonb(value), ensure_ascii=False)


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _parse_dict(value: Any) -> Dict[str, Any]:
    parsed = _parse_json(value)
    if isinstance(parsed, dict):
        return parsed
    return {}


def _parse_list(value: Any) -> List[Any]:
    parsed = _parse_json(value)
    if isinstance(parsed, list):
        return parsed
    return []


def _parse_text(value: Any) -> Optional[str]:
    parsed = _parse_json(value)
    if parsed is None:
        return None
    if isinstance(parsed, str):
        return parsed
    if isinstance(parsed, dict):
        message = parsed.get("message")
        if isinstance(message, str):
            return message
    return str(parsed)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apply_run_timestamps(run: Run) -> None:
    metadata = dict(run.metadata or {})
    now_iso = _now_iso()
    created_at = metadata.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        metadata["created_at"] = now_iso
    metadata["updated_at"] = now_iso
    run.metadata = metadata


@dataclass
class PostgresRunStore:
    pool: asyncpg.Pool
    tenant_id: str = "local"

    @staticmethod
    def _resolve_tenant(run: Run, fallback: str = "local", override: Optional[str] = None) -> str:
        if isinstance(override, str) and override:
            return override
        metadata = run.metadata or {}
        tenant = metadata.get("tenant_id")
        if isinstance(tenant, str) and tenant:
            return tenant
        return fallback

    async def save(self, run: Run, tenant_id: Optional[str] = None) -> None:
        tenant = self._resolve_tenant(run, self.tenant_id, override=tenant_id)
        run.metadata = dict(run.metadata or {})
        run.metadata["tenant_id"] = tenant
        _apply_run_timestamps(run)
        mode = run.mode if isinstance(run.mode, str) and run.mode else "live"
        project_id = run.metadata.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            project_id = None
        session_id = run.metadata.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            session_id = None
        resolved_version = run.metadata.get("resolved_version")
        if not isinstance(resolved_version, str) or not resolved_version:
            resolved_version = run.version_id
        cancellable_raw = run.metadata.get("cancellable")
        if isinstance(cancellable_raw, bool):
            cancellable = cancellable_raw
        else:
            cancellable = run.status in {"RUNNING", "WAITING_FOR_INPUT"}
        commit_point_raw = run.metadata.get("commit_point_reached")
        commit_point_reached = commit_point_raw if isinstance(commit_point_raw, bool) else None
        projected_state, projected_outputs = project_run_payload_for_transport(run.state, run.outputs, run.metadata)
        outputs_json = _jsonb(projected_outputs) if projected_outputs is not None else None
        node_outputs_json = _jsonb(run.node_outputs or {})
        branch_selection_json = _jsonb(run.branch_selection or {})
        loop_state_json = _jsonb(run.loop_state or {})
        skipped_nodes_json = _jsonb(sorted(str(node_id) for node_id in run.skipped_nodes))

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    insert into runs (
                        id, workflow_id, version_id, tenant_id, status, inputs, state, outputs, mode,
                        project_id, session_id, resolved_version, cancellable, commit_point_reached,
                        metadata, node_outputs, branch_selection, loop_state, skipped_nodes,
                        started_at, completed_at, updated_at
                    )
                    values (
                        $1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9,
                        $10, $11, $12, $13, $14,
                        $15::jsonb, $16::jsonb, $17::jsonb, $18::jsonb, $19::jsonb,
                        now(),
                        case when $5 in ('COMPLETED', 'FAILED', 'CANCELLED') then now() else null end,
                        now()
                    )
                    on conflict (id) do update
                      set workflow_id = excluded.workflow_id,
                          version_id = excluded.version_id,
                          status = excluded.status,
                          inputs = excluded.inputs,
                          state = excluded.state,
                          outputs = excluded.outputs,
                          mode = excluded.mode,
                          project_id = excluded.project_id,
                          session_id = excluded.session_id,
                          resolved_version = excluded.resolved_version,
                          cancellable = excluded.cancellable,
                          commit_point_reached = excluded.commit_point_reached,
                          metadata = excluded.metadata,
                          node_outputs = excluded.node_outputs,
                          branch_selection = excluded.branch_selection,
                          loop_state = excluded.loop_state,
                          skipped_nodes = excluded.skipped_nodes,
                          updated_at = now(),
                          started_at = coalesce(runs.started_at, excluded.started_at),
                          completed_at = case
                            when excluded.status in ('COMPLETED', 'FAILED', 'CANCELLED') then now()
                            when excluded.status in ('RUNNING', 'WAITING_FOR_INPUT') then null
                            else runs.completed_at
                          end
                    """,
                    run.id,
                    run.workflow_id,
                    run.version_id,
                    tenant,
                    run.status,
                    _jsonb(run.inputs or {}),
                    _jsonb(projected_state or {}),
                    outputs_json,
                    mode,
                    project_id,
                    session_id,
                    resolved_version,
                    cancellable,
                    commit_point_reached,
                    _jsonb(run.metadata or {}),
                    node_outputs_json,
                    branch_selection_json,
                    loop_state_json,
                    skipped_nodes_json,
                )

                await conn.execute("delete from node_runs where run_id = $1", run.id)
                node_rows = []
                for node_id, node_run in run.node_runs.items():
                    node_rows.append(
                        (
                            self._node_run_id(run.id, node_id),
                            run.id,
                            node_id,
                            node_run.status,
                            max(int(node_run.attempt), 1),
                            _jsonb(node_run.output) if node_run.output is not None else None,
                            _jsonb(node_run.last_error) if node_run.last_error is not None else None,
                            node_run.trace_id,
                            _jsonb(node_run.usage) if node_run.usage is not None else None,
                        )
                    )
                if node_rows:
                    await conn.executemany(
                        """
                        insert into node_runs (
                            id, run_id, node_id, status, attempt, output, last_error, trace_id, usage, updated_at
                        )
                        values ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9::jsonb, now())
                        """,
                        node_rows,
                    )

                await conn.execute("delete from interrupts where run_id = $1", run.id)
                interrupt_rows = []
                for interrupt in run.interrupts.values():
                    interrupt_rows.append(
                        (
                            interrupt.id,
                            interrupt.run_id,
                            interrupt.node_id,
                            tenant,
                            interrupt.type,
                            interrupt.status,
                            interrupt.prompt or "",
                            _jsonb(interrupt.input_schema) if interrupt.input_schema is not None else None,
                            bool(interrupt.allow_file_upload),
                            _jsonb(interrupt.input) if interrupt.input is not None else None,
                            _jsonb(interrupt.files) if interrupt.files is not None else None,
                            interrupt.state_target,
                        )
                    )
                if interrupt_rows:
                    await conn.executemany(
                        """
                        insert into interrupts (
                            id, run_id, node_id, tenant_id, type, status, prompt,
                            input_schema, allow_file_upload, input, files, state_target,
                            updated_at, resolved_at
                        )
                        values (
                            $1, $2, $3, $4, $5, $6, $7,
                            $8::jsonb, $9, $10::jsonb, $11::jsonb, $12,
                            now(),
                            case when $6 in ('RESOLVED', 'CANCELLED', 'EXPIRED') then now() else null end
                        )
                        """,
                        interrupt_rows,
                    )

    async def get(self, run_id: str, tenant_id: Optional[str] = None) -> Optional[Run]:
        return await self._load_run(run_id, tenant_id=tenant_id)

    async def list(
        self,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> List[Run]:
        tenant = tenant_id or self.tenant_id
        clauses: List[str] = ["tenant_id = $1"]
        params: List[Any] = [tenant]
        if workflow_id:
            params.append(workflow_id)
            clauses.append(f"workflow_id = ${len(params)}")
        if status:
            params.append(status)
            clauses.append(f"status = ${len(params)}")

        where_clause = ""
        if clauses:
            where_clause = "where " + " and ".join(clauses)

        rows = await self.pool.fetch(
            f"""
            select id
            from runs
            {where_clause}
            order by created_at desc
            limit 200
            """,
            *params,
        )
        items: List[Run] = []
        for row in rows:
            run = await self._load_run(row["id"], tenant_id=tenant)
            if run:
                items.append(run)
        return items

    async def close(self) -> None:
        return None

    async def _load_run(self, run_id: str, tenant_id: Optional[str] = None) -> Optional[Run]:
        tenant = tenant_id or self.tenant_id
        row = await self.pool.fetchrow(
            """
            select
                id, workflow_id, version_id, status, inputs, state, outputs, mode,
                project_id, session_id, resolved_version, cancellable, commit_point_reached,
                metadata,
                node_outputs, branch_selection, loop_state, skipped_nodes,
                created_at, updated_at, started_at, completed_at
            from runs
            where id = $1 and tenant_id = $2
            """,
            run_id,
            tenant,
        )
        if not row:
            return None

        node_rows = await self.pool.fetch(
            """
            select node_id, status, attempt, output, last_error, trace_id, usage
            from node_runs
            where run_id = $1
            order by node_id asc
            """,
            run_id,
        )
        interrupt_rows = await self.pool.fetch(
            """
            select
                id, run_id, node_id, type, status, prompt, input_schema,
                allow_file_upload, input, files, state_target
            from interrupts
            where run_id = $1
            order by created_at asc
            """,
            run_id,
        )

        node_runs: Dict[str, NodeRun] = {}
        for node_row in node_rows:
            node_id = str(node_row["node_id"])
            usage = _parse_json(node_row["usage"])
            node_runs[node_id] = NodeRun(
                node_id=node_id,
                status=str(node_row["status"]),
                attempt=max(int(node_row["attempt"]), 1),
                output=_parse_json(node_row["output"]),
                last_error=_parse_text(node_row["last_error"]),
                trace_id=node_row["trace_id"],
                usage=usage if isinstance(usage, dict) else None,
            )

        interrupts: Dict[str, Interrupt] = {}
        for interrupt_row in interrupt_rows:
            interrupt_id = str(interrupt_row["id"])
            input_schema = _parse_json(interrupt_row["input_schema"])
            input_payload = _parse_json(interrupt_row["input"])
            files = _parse_json(interrupt_row["files"])
            interrupts[interrupt_id] = Interrupt(
                id=interrupt_id,
                run_id=str(interrupt_row["run_id"]),
                node_id=str(interrupt_row["node_id"]),
                type=str(interrupt_row["type"]),
                status=str(interrupt_row["status"]),
                prompt=str(interrupt_row["prompt"] or ""),
                input_schema=input_schema if isinstance(input_schema, dict) else None,
                allow_file_upload=bool(interrupt_row["allow_file_upload"]),
                input=input_payload if isinstance(input_payload, dict) else None,
                files=files if isinstance(files, list) else None,
                state_target=interrupt_row["state_target"],
            )

        loop_state: Dict[str, int] = {}
        for key, value in _parse_dict(row["loop_state"]).items():
            try:
                loop_state[str(key)] = int(value)
            except Exception:
                continue

        branch_selection = {
            str(key): str(value)
            for key, value in _parse_dict(row["branch_selection"]).items()
        }

        skipped_nodes = {str(item) for item in _parse_list(row["skipped_nodes"])}
        mode = row["mode"] if isinstance(row["mode"], str) and row["mode"] else "live"
        metadata = _parse_dict(row["metadata"])
        if row["project_id"] and not metadata.get("project_id"):
            metadata["project_id"] = row["project_id"]
        if row["session_id"] and not metadata.get("session_id"):
            metadata["session_id"] = row["session_id"]
        if row["resolved_version"] and not metadata.get("resolved_version"):
            metadata["resolved_version"] = row["resolved_version"]
        if isinstance(row["cancellable"], bool):
            metadata["cancellable"] = row["cancellable"]
        if isinstance(row["commit_point_reached"], bool):
            metadata["commit_point_reached"] = row["commit_point_reached"]
        if row["created_at"]:
            metadata["created_at"] = row["created_at"].isoformat()
        if row["updated_at"]:
            metadata["updated_at"] = row["updated_at"].isoformat()
        if row["started_at"]:
            metadata["started_at"] = row["started_at"].isoformat()
        if row["completed_at"]:
            metadata["completed_at"] = row["completed_at"].isoformat()

        return Run(
            id=str(row["id"]),
            workflow_id=str(row["workflow_id"]),
            version_id=str(row["version_id"]),
            status=str(row["status"]),
            inputs=_parse_dict(row["inputs"]),
            state=_parse_dict(row["state"]),
            mode=mode,
            outputs=_parse_json(row["outputs"]),
            metadata=metadata,
            node_runs=node_runs,
            node_outputs=_parse_dict(row["node_outputs"]),
            interrupts=interrupts,
            branch_selection=branch_selection,
            loop_state=loop_state,
            skipped_nodes=skipped_nodes,
        )

    @staticmethod
    def _node_run_id(run_id: str, node_id: str) -> str:
        return f"nr_{run_id}_{node_id}"


async def create_run_store(workflow_store: Any | None, tenant_id: str = "local") -> InMemoryRunStore | PostgresRunStore:
    pool = getattr(workflow_store, "pool", None)
    if isinstance(pool, asyncpg.Pool):
        return PostgresRunStore(pool=pool, tenant_id=tenant_id)
    return InMemoryRunStore(tenant_id=tenant_id)
