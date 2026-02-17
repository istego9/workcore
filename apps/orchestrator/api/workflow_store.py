from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg

from apps.orchestrator.runtime.env import get_env, load_env


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _hash_content(content: Dict[str, Any]) -> str:
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _jsonb(value: Any) -> str:
    return json.dumps(value)


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


class WorkflowNotFoundError(RuntimeError):
    pass


class WorkflowConflictError(RuntimeError):
    pass


@dataclass
class WorkflowRecord:
    workflow_id: str
    tenant_id: str
    project_id: Optional[str]
    name: str
    description: Optional[str]
    draft: Dict[str, Any]
    active_version_id: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass
class WorkflowSummary:
    workflow_id: str
    tenant_id: str
    project_id: Optional[str]
    name: str
    description: Optional[str]
    active_version_id: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass
class WorkflowVersionRecord:
    version_id: str
    workflow_id: str
    tenant_id: str
    version_number: int
    hash: str
    content: Dict[str, Any]
    created_at: datetime


class InMemoryWorkflowStore:
    def __init__(self, tenant_id: str = "local") -> None:
        self.tenant_id = tenant_id
        self.workflows: Dict[str, WorkflowRecord] = {}
        self.versions: Dict[str, WorkflowVersionRecord] = {}
        self.workflow_versions: Dict[str, List[str]] = {}

    async def create_workflow(
        self,
        name: str,
        description: Optional[str],
        draft: Dict[str, Any],
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> WorkflowRecord:
        workflow_id = _new_id("wf")
        tenant = tenant_id or self.tenant_id
        project = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
        now = _now()
        record = WorkflowRecord(
            workflow_id=workflow_id,
            tenant_id=tenant,
            project_id=project,
            name=name,
            description=description,
            draft=draft,
            active_version_id=None,
            created_at=now,
            updated_at=now,
        )
        self.workflows[workflow_id] = record
        self.workflow_versions[workflow_id] = []
        return record

    async def get_workflow(
        self,
        workflow_id: str,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> WorkflowRecord:
        record = self.workflows.get(workflow_id)
        tenant = tenant_id or self.tenant_id
        project = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
        if not record or record.tenant_id != tenant:
            raise WorkflowNotFoundError("workflow not found")
        if project is not None and record.project_id != project:
            raise WorkflowNotFoundError("workflow not found")
        return record

    async def update_meta(
        self,
        workflow_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        update_name: bool = False,
        update_description: bool = False,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> WorkflowRecord:
        record = await self.get_workflow(workflow_id, tenant_id=tenant_id, project_id=project_id)
        if update_name:
            record.name = name or record.name
        if update_description:
            record.description = description
        record.updated_at = _now()
        return record

    async def list_workflows(
        self,
        limit: int = 50,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[WorkflowSummary]:
        tenant = tenant_id or self.tenant_id
        project = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
        records = sorted(
            [
                item
                for item in self.workflows.values()
                if item.tenant_id == tenant and (project is None or item.project_id == project)
            ],
            key=lambda item: item.updated_at,
            reverse=True,
        )
        return [
            WorkflowSummary(
                workflow_id=record.workflow_id,
                tenant_id=record.tenant_id,
                project_id=record.project_id,
                name=record.name,
                description=record.description,
                active_version_id=record.active_version_id,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record in records[:limit]
        ]

    async def update_draft(
        self,
        workflow_id: str,
        draft: Dict[str, Any],
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> WorkflowRecord:
        record = await self.get_workflow(workflow_id, tenant_id=tenant_id, project_id=project_id)
        record.draft = draft
        record.updated_at = _now()
        return record

    async def publish(
        self,
        workflow_id: str,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> WorkflowVersionRecord:
        record = await self.get_workflow(workflow_id, tenant_id=tenant_id, project_id=project_id)
        version_number = len(self.workflow_versions.get(workflow_id, [])) + 1
        version_id = _new_id("wfv")
        version = WorkflowVersionRecord(
            version_id=version_id,
            workflow_id=workflow_id,
            tenant_id=record.tenant_id,
            version_number=version_number,
            hash=_hash_content(record.draft),
            content=record.draft,
            created_at=_now(),
        )
        self.versions[version_id] = version
        self.workflow_versions.setdefault(workflow_id, []).append(version_id)
        record.active_version_id = version_id
        record.updated_at = _now()
        return version

    async def rollback(
        self,
        workflow_id: str,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> WorkflowRecord:
        record = await self.get_workflow(workflow_id, tenant_id=tenant_id, project_id=project_id)
        if not record.active_version_id:
            raise WorkflowConflictError("workflow has no active version")
        version = self.versions.get(record.active_version_id)
        if not version:
            raise WorkflowConflictError("active version not found")
        record.draft = version.content
        record.updated_at = _now()
        return record

    async def list_versions(
        self,
        workflow_id: str,
        limit: int = 50,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[WorkflowVersionRecord]:
        tenant = tenant_id or self.tenant_id
        project = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
        record = self.workflows.get(workflow_id)
        if not record or record.tenant_id != tenant:
            raise WorkflowNotFoundError("workflow not found")
        if project is not None and record.project_id != project:
            raise WorkflowNotFoundError("workflow not found")
        version_ids = list(self.workflow_versions.get(workflow_id, []))
        versions = [self.versions[vid] for vid in reversed(version_ids)]
        versions = [version for version in versions if version.tenant_id == tenant]
        return versions[:limit]

    async def get_version(self, version_id: str, tenant_id: Optional[str] = None) -> WorkflowVersionRecord:
        version = self.versions.get(version_id)
        tenant = tenant_id or self.tenant_id
        if not version or version.tenant_id != tenant:
            raise WorkflowNotFoundError("workflow version not found")
        return version

    async def delete_workflow(
        self,
        workflow_id: str,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> None:
        tenant = tenant_id or self.tenant_id
        record = self.workflows.get(workflow_id)
        project = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
        if not record or record.tenant_id != tenant:
            raise WorkflowNotFoundError("workflow not found")
        if project is not None and record.project_id != project:
            raise WorkflowNotFoundError("workflow not found")
        version_ids = self.workflow_versions.pop(workflow_id, [])
        for version_id in version_ids:
            self.versions.pop(version_id, None)
        self.workflows.pop(workflow_id, None)

    async def close(self) -> None:
        return None


class PostgresWorkflowStore:
    def __init__(self, pool: asyncpg.Pool, tenant_id: str = "local") -> None:
        self.pool = pool
        self.tenant_id = tenant_id

    async def create_workflow(
        self,
        name: str,
        description: Optional[str],
        draft: Dict[str, Any],
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> WorkflowRecord:
        workflow_id = _new_id("wf")
        tenant = tenant_id or self.tenant_id
        project = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
        await self.pool.execute(
            """
            insert into workflows (id, tenant_id, project_id, name, description, draft, active_version_id)
            values ($1, $2, $3, $4, $5, $6::jsonb, $7)
            """,
            workflow_id,
            tenant,
            project,
            name,
            description,
            _jsonb(draft),
            None,
        )
        return await self.get_workflow(workflow_id, tenant_id=tenant, project_id=project)

    async def get_workflow(
        self,
        workflow_id: str,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> WorkflowRecord:
        tenant = tenant_id or self.tenant_id
        project = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
        row = await self.pool.fetchrow(
            """
            select id, tenant_id, project_id, name, description, draft, active_version_id, created_at, updated_at
            from workflows
            where id = $1 and tenant_id = $2
              and ($3::text is null or project_id = $3)
            """,
            workflow_id,
            tenant,
            project,
        )
        if not row:
            raise WorkflowNotFoundError("workflow not found")
        return WorkflowRecord(
            workflow_id=row["id"],
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            name=row["name"],
            description=row["description"],
            draft=_parse_json(row["draft"]) or {},
            active_version_id=row["active_version_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def update_meta(
        self,
        workflow_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        update_name: bool = False,
        update_description: bool = False,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> WorkflowRecord:
        tenant = tenant_id or self.tenant_id
        project = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
        result = await self.pool.execute(
            """
            update workflows
            set
                name = case when $3 then $1 else name end,
                description = case when $4 then $2 else description end,
                updated_at = now()
            where id = $5 and tenant_id = $6
              and ($7::text is null or project_id = $7)
            """,
            name,
            description,
            update_name,
            update_description,
            workflow_id,
            tenant,
            project,
        )
        if result == "UPDATE 0":
            raise WorkflowNotFoundError("workflow not found")
        return await self.get_workflow(workflow_id, tenant_id=tenant, project_id=project)

    async def list_workflows(
        self,
        limit: int = 50,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[WorkflowSummary]:
        tenant = tenant_id or self.tenant_id
        project = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
        rows = await self.pool.fetch(
            """
            select id, tenant_id, project_id, name, description, active_version_id, created_at, updated_at
            from workflows
            where tenant_id = $1
              and ($2::text is null or project_id = $2)
            order by updated_at desc
            limit $3
            """,
            tenant,
            project,
            limit,
        )
        return [
            WorkflowSummary(
                workflow_id=row["id"],
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                name=row["name"],
                description=row["description"],
                active_version_id=row["active_version_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def update_draft(
        self,
        workflow_id: str,
        draft: Dict[str, Any],
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> WorkflowRecord:
        tenant = tenant_id or self.tenant_id
        project = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
        result = await self.pool.execute(
            """
            update workflows
            set draft = $1::jsonb, updated_at = now()
            where id = $2 and tenant_id = $3
              and ($4::text is null or project_id = $4)
            """,
            _jsonb(draft),
            workflow_id,
            tenant,
            project,
        )
        if result == "UPDATE 0":
            raise WorkflowNotFoundError("workflow not found")
        return await self.get_workflow(workflow_id, tenant_id=tenant, project_id=project)

    async def publish(
        self,
        workflow_id: str,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> WorkflowVersionRecord:
        tenant = tenant_id or self.tenant_id
        record = await self.get_workflow(workflow_id, tenant_id=tenant, project_id=project_id)
        version_number = await self.pool.fetchval(
            """
            select coalesce(max(version_number), 0) + 1
            from workflow_versions
            where workflow_id = $1 and tenant_id = $2
            """,
            workflow_id,
            tenant,
        )
        version_id = _new_id("wfv")
        hash_value = _hash_content(record.draft)
        await self.pool.execute(
            """
            insert into workflow_versions (id, workflow_id, tenant_id, version_number, hash, content)
            values ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            version_id,
            workflow_id,
            tenant,
            version_number,
            hash_value,
            _jsonb(record.draft),
        )
        await self.pool.execute(
            """
            update workflows
            set active_version_id = $1, updated_at = now()
            where id = $2 and tenant_id = $3
            """,
            version_id,
            workflow_id,
            tenant,
        )
        return await self.get_version(version_id, tenant_id=tenant)

    async def rollback(
        self,
        workflow_id: str,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> WorkflowRecord:
        tenant = tenant_id or self.tenant_id
        record = await self.get_workflow(workflow_id, tenant_id=tenant, project_id=project_id)
        if not record.active_version_id:
            raise WorkflowConflictError("workflow has no active version")
        version = await self.get_version(record.active_version_id, tenant_id=tenant)
        await self.pool.execute(
            """
            update workflows
            set draft = $1::jsonb, updated_at = now()
            where id = $2 and tenant_id = $3
            """,
            _jsonb(version.content),
            workflow_id,
            tenant,
        )
        return await self.get_workflow(workflow_id, tenant_id=tenant, project_id=project_id)

    async def list_versions(
        self,
        workflow_id: str,
        limit: int = 50,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[WorkflowVersionRecord]:
        tenant = tenant_id or self.tenant_id
        project = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
        rows = await self.pool.fetch(
            """
            select
              v.id,
              v.workflow_id,
              v.tenant_id,
              v.version_number,
              v.hash,
              v.content,
              v.created_at
            from workflow_versions v
            join workflows w on w.id = v.workflow_id and w.tenant_id = v.tenant_id
            where v.workflow_id = $1 and v.tenant_id = $2
              and ($3::text is null or w.project_id = $3)
            order by version_number desc
            limit $4
            """,
            workflow_id,
            tenant,
            project,
            limit,
        )
        if not rows:
            workflow_exists = await self.pool.fetchval(
                """
                select 1
                from workflows
                where id = $1 and tenant_id = $2
                  and ($3::text is null or project_id = $3)
                """,
                workflow_id,
                tenant,
                project,
            )
            if not workflow_exists:
                raise WorkflowNotFoundError("workflow not found")
        return [
            WorkflowVersionRecord(
                version_id=row["id"],
                workflow_id=row["workflow_id"],
                tenant_id=row["tenant_id"],
                version_number=row["version_number"],
                hash=row["hash"],
                content=_parse_json(row["content"]) or {},
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def get_version(self, version_id: str, tenant_id: Optional[str] = None) -> WorkflowVersionRecord:
        tenant = tenant_id or self.tenant_id
        row = await self.pool.fetchrow(
            """
            select id, workflow_id, tenant_id, version_number, hash, content, created_at
            from workflow_versions
            where id = $1 and tenant_id = $2
            """,
            version_id,
            tenant,
        )
        if not row:
            raise WorkflowNotFoundError("workflow version not found")
        return WorkflowVersionRecord(
            version_id=row["id"],
            workflow_id=row["workflow_id"],
            tenant_id=row["tenant_id"],
            version_number=row["version_number"],
            hash=row["hash"],
            content=_parse_json(row["content"]) or {},
            created_at=row["created_at"],
        )

    async def delete_workflow(
        self,
        workflow_id: str,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> None:
        tenant = tenant_id or self.tenant_id
        project = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
        result = await self.pool.execute(
            """
            delete from workflows
            where id = $1 and tenant_id = $2
              and ($3::text is null or project_id = $3)
            """,
            workflow_id,
            tenant,
            project,
        )
        if result == "DELETE 0":
            raise WorkflowNotFoundError("workflow not found")

    async def close(self) -> None:
        await self.pool.close()


async def create_workflow_store() -> InMemoryWorkflowStore | PostgresWorkflowStore:
    load_env()
    database_url = get_env("DATABASE_URL") or get_env("CHATKIT_DATABASE_URL")
    if not database_url:
        return InMemoryWorkflowStore()
    pool = await asyncpg.create_pool(database_url)
    return PostgresWorkflowStore(pool)
