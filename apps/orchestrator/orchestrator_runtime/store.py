from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, Sequence

import asyncpg


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _jsonb(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _parse_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


def _parse_dict(value: Any) -> Dict[str, Any]:
    parsed = _parse_json(value, {})
    return parsed if isinstance(parsed, dict) else {}


def _parse_list(value: Any) -> List[Any]:
    parsed = _parse_json(value, [])
    return parsed if isinstance(parsed, list) else []


@dataclass
class ProjectRecord:
    project_id: str
    tenant_id: str
    default_orchestrator_id: Optional[str]
    settings: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ProjectConflictError(RuntimeError):
    """Raised when attempting to create a project that already exists."""


@dataclass
class OrchestratorConfigRecord:
    tenant_id: str
    project_id: str
    orchestrator_id: str
    name: str
    routing_policy: Dict[str, Any]
    fallback_workflow_id: Optional[str]
    prompt_profile: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass
class WorkflowDefinitionRecord:
    tenant_id: str
    project_id: str
    workflow_id: str
    name: str
    description: str
    tags: List[str]
    examples: List[str]
    active: bool
    is_fallback: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class SessionStateRecord:
    tenant_id: str
    project_id: str
    session_id: str
    orchestrator_id: Optional[str]
    active_run_id: Optional[str]
    pending_disambiguation: bool
    pending_question: Optional[str]
    pending_options: List[str]
    disambiguation_turns: int
    last_user_message_id: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass
class WorkflowStackEntryRecord:
    id: str
    tenant_id: str
    project_id: str
    session_id: str
    run_id: str
    stack_index: int
    transition_reason: str
    from_run_id: Optional[str]
    created_at: datetime


@dataclass
class OrchestrationDecisionRecord:
    decision_id: str
    tenant_id: str
    project_id: str
    orchestrator_id: Optional[str]
    session_id: str
    message_id: str
    mode: str
    active_run_id: Optional[str]
    context_ref: Dict[str, Any]
    candidates: List[Dict[str, Any]]
    chosen_action: str
    chosen_workflow_id: Optional[str]
    confidence: float
    latency_ms: int
    model_id: Optional[str]
    error_code: Optional[str]
    created_at: datetime = field(default_factory=_now)


class OrchestrationStore(Protocol):
    async def create_project(
        self,
        project_id: str,
        tenant_id: str,
        default_orchestrator_id: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> ProjectRecord:
        ...

    async def get_project(self, project_id: str, tenant_id: str) -> Optional[ProjectRecord]:
        ...

    async def upsert_project(
        self,
        project_id: str,
        tenant_id: str,
        default_orchestrator_id: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> ProjectRecord:
        ...

    async def get_orchestrator_config(
        self,
        project_id: str,
        orchestrator_id: str,
        tenant_id: str,
    ) -> Optional[OrchestratorConfigRecord]:
        ...

    async def list_orchestrator_configs(self, project_id: str, tenant_id: str) -> List[OrchestratorConfigRecord]:
        ...

    async def upsert_orchestrator_config(
        self,
        project_id: str,
        orchestrator_id: str,
        name: str,
        tenant_id: str,
        routing_policy: Optional[Dict[str, Any]] = None,
        fallback_workflow_id: Optional[str] = None,
        prompt_profile: Optional[str] = None,
        set_as_default: bool = False,
    ) -> OrchestratorConfigRecord:
        ...

    async def get_workflow_definition(
        self,
        project_id: str,
        workflow_id: str,
        tenant_id: str,
    ) -> Optional[WorkflowDefinitionRecord]:
        ...

    async def list_workflow_definitions(
        self,
        project_id: str,
        tenant_id: str,
        active_only: bool = True,
    ) -> List[WorkflowDefinitionRecord]:
        ...

    async def upsert_workflow_definition(
        self,
        project_id: str,
        workflow_id: str,
        tenant_id: str,
        name: str,
        description: str,
        tags: Optional[Sequence[str]] = None,
        examples: Optional[Sequence[str]] = None,
        active: bool = True,
        is_fallback: bool = False,
    ) -> WorkflowDefinitionRecord:
        ...

    async def get_fallback_workflow_definition(
        self,
        project_id: str,
        tenant_id: str,
    ) -> Optional[WorkflowDefinitionRecord]:
        ...

    async def get_session_state(
        self,
        project_id: str,
        session_id: str,
        tenant_id: str,
    ) -> Optional[SessionStateRecord]:
        ...

    async def save_session_state(self, state: SessionStateRecord) -> SessionStateRecord:
        ...

    async def append_stack_entry(
        self,
        project_id: str,
        session_id: str,
        tenant_id: str,
        run_id: str,
        transition_reason: str,
        from_run_id: Optional[str] = None,
    ) -> WorkflowStackEntryRecord:
        ...

    async def list_stack(self, project_id: str, session_id: str, tenant_id: str) -> List[WorkflowStackEntryRecord]:
        ...

    async def save_decision(self, decision: OrchestrationDecisionRecord) -> OrchestrationDecisionRecord:
        ...

    async def list_recent_decisions(
        self,
        project_id: str,
        session_id: str,
        tenant_id: str,
        limit: int = 5,
    ) -> List[OrchestrationDecisionRecord]:
        ...

    async def close(self) -> None:
        ...


@dataclass
class InMemoryOrchestrationStore:
    projects: Dict[tuple[str, str], ProjectRecord] = field(default_factory=dict)
    orchestrator_configs: Dict[tuple[str, str, str], OrchestratorConfigRecord] = field(default_factory=dict)
    workflow_definitions: Dict[tuple[str, str, str], WorkflowDefinitionRecord] = field(default_factory=dict)
    session_states: Dict[tuple[str, str, str], SessionStateRecord] = field(default_factory=dict)
    stack_entries: Dict[tuple[str, str, str], List[WorkflowStackEntryRecord]] = field(default_factory=dict)
    decisions: Dict[tuple[str, str, str], List[OrchestrationDecisionRecord]] = field(default_factory=dict)

    async def create_project(
        self,
        project_id: str,
        tenant_id: str,
        default_orchestrator_id: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> ProjectRecord:
        key = (tenant_id, project_id)
        if key in self.projects:
            raise ProjectConflictError("project already exists")
        now = _now()
        record = ProjectRecord(
            project_id=project_id,
            tenant_id=tenant_id,
            default_orchestrator_id=default_orchestrator_id,
            settings=dict(settings or {}),
            created_at=now,
            updated_at=now,
        )
        self.projects[key] = record
        return record

    async def get_project(self, project_id: str, tenant_id: str) -> Optional[ProjectRecord]:
        return self.projects.get((tenant_id, project_id))

    async def upsert_project(
        self,
        project_id: str,
        tenant_id: str,
        default_orchestrator_id: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> ProjectRecord:
        key = (tenant_id, project_id)
        existing = self.projects.get(key)
        now = _now()
        if existing:
            if default_orchestrator_id:
                existing.default_orchestrator_id = default_orchestrator_id
            if settings is not None:
                existing.settings = dict(settings)
            existing.updated_at = now
            return existing
        record = ProjectRecord(
            project_id=project_id,
            tenant_id=tenant_id,
            default_orchestrator_id=default_orchestrator_id,
            settings=dict(settings or {}),
            created_at=now,
            updated_at=now,
        )
        self.projects[key] = record
        return record

    async def get_orchestrator_config(
        self,
        project_id: str,
        orchestrator_id: str,
        tenant_id: str,
    ) -> Optional[OrchestratorConfigRecord]:
        return self.orchestrator_configs.get((tenant_id, project_id, orchestrator_id))

    async def list_orchestrator_configs(self, project_id: str, tenant_id: str) -> List[OrchestratorConfigRecord]:
        items = [
            item
            for item in self.orchestrator_configs.values()
            if item.project_id == project_id and item.tenant_id == tenant_id
        ]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items

    async def upsert_orchestrator_config(
        self,
        project_id: str,
        orchestrator_id: str,
        name: str,
        tenant_id: str,
        routing_policy: Optional[Dict[str, Any]] = None,
        fallback_workflow_id: Optional[str] = None,
        prompt_profile: Optional[str] = None,
        set_as_default: bool = False,
    ) -> OrchestratorConfigRecord:
        key = (tenant_id, project_id, orchestrator_id)
        now = _now()
        existing = self.orchestrator_configs.get(key)
        if existing:
            existing.name = name
            if routing_policy is not None:
                existing.routing_policy = dict(routing_policy)
            existing.fallback_workflow_id = fallback_workflow_id
            existing.prompt_profile = prompt_profile
            existing.updated_at = now
            record = existing
        else:
            record = OrchestratorConfigRecord(
                tenant_id=tenant_id,
                project_id=project_id,
                orchestrator_id=orchestrator_id,
                name=name,
                routing_policy=dict(routing_policy or {}),
                fallback_workflow_id=fallback_workflow_id,
                prompt_profile=prompt_profile,
                created_at=now,
                updated_at=now,
            )
            self.orchestrator_configs[key] = record

        if set_as_default:
            project = self.projects.get((tenant_id, project_id))
            if project:
                project.default_orchestrator_id = orchestrator_id
                project.updated_at = now
        return record

    async def get_workflow_definition(
        self,
        project_id: str,
        workflow_id: str,
        tenant_id: str,
    ) -> Optional[WorkflowDefinitionRecord]:
        return self.workflow_definitions.get((tenant_id, project_id, workflow_id))

    async def list_workflow_definitions(
        self,
        project_id: str,
        tenant_id: str,
        active_only: bool = True,
    ) -> List[WorkflowDefinitionRecord]:
        items = [
            item
            for item in self.workflow_definitions.values()
            if item.project_id == project_id and item.tenant_id == tenant_id and (item.active or not active_only)
        ]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items

    async def upsert_workflow_definition(
        self,
        project_id: str,
        workflow_id: str,
        tenant_id: str,
        name: str,
        description: str,
        tags: Optional[Sequence[str]] = None,
        examples: Optional[Sequence[str]] = None,
        active: bool = True,
        is_fallback: bool = False,
    ) -> WorkflowDefinitionRecord:
        key = (tenant_id, project_id, workflow_id)
        now = _now()
        existing = self.workflow_definitions.get(key)
        if existing:
            existing.name = name
            existing.description = description
            existing.tags = [str(item) for item in (tags or [])]
            existing.examples = [str(item) for item in (examples or [])]
            existing.active = bool(active)
            existing.is_fallback = bool(is_fallback)
            existing.updated_at = now
            return existing
        record = WorkflowDefinitionRecord(
            tenant_id=tenant_id,
            project_id=project_id,
            workflow_id=workflow_id,
            name=name,
            description=description,
            tags=[str(item) for item in (tags or [])],
            examples=[str(item) for item in (examples or [])],
            active=bool(active),
            is_fallback=bool(is_fallback),
            created_at=now,
            updated_at=now,
        )
        self.workflow_definitions[key] = record
        return record

    async def get_fallback_workflow_definition(self, project_id: str, tenant_id: str) -> Optional[WorkflowDefinitionRecord]:
        items = [
            item
            for item in self.workflow_definitions.values()
            if item.project_id == project_id and item.tenant_id == tenant_id and item.active and item.is_fallback
        ]
        if not items:
            return None
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[0]

    async def get_session_state(self, project_id: str, session_id: str, tenant_id: str) -> Optional[SessionStateRecord]:
        return self.session_states.get((tenant_id, project_id, session_id))

    async def save_session_state(self, state: SessionStateRecord) -> SessionStateRecord:
        key = (state.tenant_id, state.project_id, state.session_id)
        now = _now()
        existing = self.session_states.get(key)
        if existing:
            existing.orchestrator_id = state.orchestrator_id
            existing.active_run_id = state.active_run_id
            existing.pending_disambiguation = state.pending_disambiguation
            existing.pending_question = state.pending_question
            existing.pending_options = list(state.pending_options)
            existing.disambiguation_turns = int(state.disambiguation_turns)
            existing.last_user_message_id = state.last_user_message_id
            existing.updated_at = now
            return existing
        state.created_at = now
        state.updated_at = now
        self.session_states[key] = state
        return state

    async def append_stack_entry(
        self,
        project_id: str,
        session_id: str,
        tenant_id: str,
        run_id: str,
        transition_reason: str,
        from_run_id: Optional[str] = None,
    ) -> WorkflowStackEntryRecord:
        key = (tenant_id, project_id, session_id)
        items = self.stack_entries.setdefault(key, [])
        entry = WorkflowStackEntryRecord(
            id=_new_id("wstk"),
            tenant_id=tenant_id,
            project_id=project_id,
            session_id=session_id,
            run_id=run_id,
            stack_index=len(items),
            transition_reason=transition_reason,
            from_run_id=from_run_id,
            created_at=_now(),
        )
        items.append(entry)
        return entry

    async def list_stack(self, project_id: str, session_id: str, tenant_id: str) -> List[WorkflowStackEntryRecord]:
        key = (tenant_id, project_id, session_id)
        return list(self.stack_entries.get(key, []))

    async def save_decision(self, decision: OrchestrationDecisionRecord) -> OrchestrationDecisionRecord:
        key = (decision.tenant_id, decision.project_id, decision.session_id)
        self.decisions.setdefault(key, []).append(decision)
        return decision

    async def list_recent_decisions(
        self,
        project_id: str,
        session_id: str,
        tenant_id: str,
        limit: int = 5,
    ) -> List[OrchestrationDecisionRecord]:
        key = (tenant_id, project_id, session_id)
        items = list(self.decisions.get(key, []))
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[:limit]

    async def close(self) -> None:
        return None


@dataclass
class PostgresOrchestrationStore:
    pool: asyncpg.Pool

    async def create_project(
        self,
        project_id: str,
        tenant_id: str,
        default_orchestrator_id: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> ProjectRecord:
        row = await self.pool.fetchrow(
            """
            insert into projects (project_id, tenant_id, default_orchestrator_id, settings)
            values ($1, $2, $3, $4::jsonb)
            on conflict (tenant_id, project_id) do nothing
            returning project_id, tenant_id, default_orchestrator_id, settings, created_at, updated_at
            """,
            project_id,
            tenant_id,
            default_orchestrator_id,
            _jsonb(settings or {}),
        )
        if not row:
            raise ProjectConflictError("project already exists")
        return ProjectRecord(
            project_id=row["project_id"],
            tenant_id=row["tenant_id"],
            default_orchestrator_id=row["default_orchestrator_id"],
            settings=_parse_dict(row["settings"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def get_project(self, project_id: str, tenant_id: str) -> Optional[ProjectRecord]:
        row = await self.pool.fetchrow(
            """
            select project_id, tenant_id, default_orchestrator_id, settings, created_at, updated_at
            from projects
            where project_id = $1 and tenant_id = $2
            """,
            project_id,
            tenant_id,
        )
        if not row:
            return None
        return ProjectRecord(
            project_id=row["project_id"],
            tenant_id=row["tenant_id"],
            default_orchestrator_id=row["default_orchestrator_id"],
            settings=_parse_dict(row["settings"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def upsert_project(
        self,
        project_id: str,
        tenant_id: str,
        default_orchestrator_id: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> ProjectRecord:
        await self.pool.execute(
            """
            insert into projects (project_id, tenant_id, default_orchestrator_id, settings)
            values ($1, $2, $3, $4::jsonb)
            on conflict (tenant_id, project_id) do update
              set default_orchestrator_id = coalesce(excluded.default_orchestrator_id, projects.default_orchestrator_id),
                  settings = coalesce(excluded.settings, projects.settings),
                  updated_at = now()
            """,
            project_id,
            tenant_id,
            default_orchestrator_id,
            _jsonb(settings or {}),
        )
        loaded = await self.get_project(project_id, tenant_id)
        if loaded is None:
            raise RuntimeError("failed to upsert project")
        return loaded

    async def get_orchestrator_config(
        self,
        project_id: str,
        orchestrator_id: str,
        tenant_id: str,
    ) -> Optional[OrchestratorConfigRecord]:
        row = await self.pool.fetchrow(
            """
            select
              tenant_id, project_id, orchestrator_id, name, routing_policy, fallback_workflow_id, prompt_profile,
              created_at, updated_at
            from orchestrator_configs
            where tenant_id = $1 and project_id = $2 and orchestrator_id = $3
            """,
            tenant_id,
            project_id,
            orchestrator_id,
        )
        if not row:
            return None
        return OrchestratorConfigRecord(
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            orchestrator_id=row["orchestrator_id"],
            name=row["name"],
            routing_policy=_parse_dict(row["routing_policy"]),
            fallback_workflow_id=row["fallback_workflow_id"],
            prompt_profile=row["prompt_profile"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def list_orchestrator_configs(self, project_id: str, tenant_id: str) -> List[OrchestratorConfigRecord]:
        rows = await self.pool.fetch(
            """
            select
              tenant_id, project_id, orchestrator_id, name, routing_policy, fallback_workflow_id, prompt_profile,
              created_at, updated_at
            from orchestrator_configs
            where tenant_id = $1 and project_id = $2
            order by updated_at desc
            """,
            tenant_id,
            project_id,
        )
        return [
            OrchestratorConfigRecord(
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                orchestrator_id=row["orchestrator_id"],
                name=row["name"],
                routing_policy=_parse_dict(row["routing_policy"]),
                fallback_workflow_id=row["fallback_workflow_id"],
                prompt_profile=row["prompt_profile"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def upsert_orchestrator_config(
        self,
        project_id: str,
        orchestrator_id: str,
        name: str,
        tenant_id: str,
        routing_policy: Optional[Dict[str, Any]] = None,
        fallback_workflow_id: Optional[str] = None,
        prompt_profile: Optional[str] = None,
        set_as_default: bool = False,
    ) -> OrchestratorConfigRecord:
        await self.pool.execute(
            """
            insert into orchestrator_configs (
              tenant_id, project_id, orchestrator_id, name, routing_policy, fallback_workflow_id, prompt_profile
            )
            values ($1, $2, $3, $4, $5::jsonb, $6, $7)
            on conflict (tenant_id, project_id, orchestrator_id) do update
              set name = excluded.name,
                  routing_policy = excluded.routing_policy,
                  fallback_workflow_id = excluded.fallback_workflow_id,
                  prompt_profile = excluded.prompt_profile,
                  updated_at = now()
            """,
            tenant_id,
            project_id,
            orchestrator_id,
            name,
            _jsonb(routing_policy or {}),
            fallback_workflow_id,
            prompt_profile,
        )
        if set_as_default:
            await self.pool.execute(
                """
                update projects
                set default_orchestrator_id = $1, updated_at = now()
                where tenant_id = $2 and project_id = $3
                """,
                orchestrator_id,
                tenant_id,
                project_id,
            )
        loaded = await self.get_orchestrator_config(project_id, orchestrator_id, tenant_id)
        if loaded is None:
            raise RuntimeError("failed to upsert orchestrator config")
        return loaded

    async def get_workflow_definition(
        self,
        project_id: str,
        workflow_id: str,
        tenant_id: str,
    ) -> Optional[WorkflowDefinitionRecord]:
        row = await self.pool.fetchrow(
            """
            select
              tenant_id, project_id, workflow_id, name, description, tags, examples, active, is_fallback,
              created_at, updated_at
            from workflow_definitions
            where tenant_id = $1 and project_id = $2 and workflow_id = $3
            """,
            tenant_id,
            project_id,
            workflow_id,
        )
        if not row:
            return None
        return WorkflowDefinitionRecord(
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            workflow_id=row["workflow_id"],
            name=row["name"],
            description=row["description"],
            tags=[str(item) for item in (row["tags"] or [])],
            examples=[str(item) for item in (row["examples"] or [])],
            active=bool(row["active"]),
            is_fallback=bool(row["is_fallback"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def list_workflow_definitions(
        self,
        project_id: str,
        tenant_id: str,
        active_only: bool = True,
    ) -> List[WorkflowDefinitionRecord]:
        if active_only:
            rows = await self.pool.fetch(
                """
                select
                  tenant_id, project_id, workflow_id, name, description, tags, examples, active, is_fallback,
                  created_at, updated_at
                from workflow_definitions
                where tenant_id = $1 and project_id = $2 and active = true
                order by updated_at desc
                """,
                tenant_id,
                project_id,
            )
        else:
            rows = await self.pool.fetch(
                """
                select
                  tenant_id, project_id, workflow_id, name, description, tags, examples, active, is_fallback,
                  created_at, updated_at
                from workflow_definitions
                where tenant_id = $1 and project_id = $2
                order by updated_at desc
                """,
                tenant_id,
                project_id,
            )
        return [
            WorkflowDefinitionRecord(
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                workflow_id=row["workflow_id"],
                name=row["name"],
                description=row["description"],
                tags=[str(item) for item in (row["tags"] or [])],
                examples=[str(item) for item in (row["examples"] or [])],
                active=bool(row["active"]),
                is_fallback=bool(row["is_fallback"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def upsert_workflow_definition(
        self,
        project_id: str,
        workflow_id: str,
        tenant_id: str,
        name: str,
        description: str,
        tags: Optional[Sequence[str]] = None,
        examples: Optional[Sequence[str]] = None,
        active: bool = True,
        is_fallback: bool = False,
    ) -> WorkflowDefinitionRecord:
        tags_value = [str(item) for item in (tags or [])]
        examples_value = [str(item) for item in (examples or [])]
        await self.pool.execute(
            """
            insert into workflow_definitions (
              tenant_id, project_id, workflow_id, name, description, tags, examples, active, is_fallback
            )
            values ($1, $2, $3, $4, $5, $6::text[], $7::text[], $8, $9)
            on conflict (tenant_id, project_id, workflow_id) do update
              set name = excluded.name,
                  description = excluded.description,
                  tags = excluded.tags,
                  examples = excluded.examples,
                  active = excluded.active,
                  is_fallback = excluded.is_fallback,
                  updated_at = now()
            """,
            tenant_id,
            project_id,
            workflow_id,
            name,
            description,
            tags_value,
            examples_value,
            bool(active),
            bool(is_fallback),
        )
        loaded = await self.get_workflow_definition(project_id, workflow_id, tenant_id)
        if loaded is None:
            raise RuntimeError("failed to upsert workflow definition")
        return loaded

    async def get_fallback_workflow_definition(self, project_id: str, tenant_id: str) -> Optional[WorkflowDefinitionRecord]:
        row = await self.pool.fetchrow(
            """
            select
              tenant_id, project_id, workflow_id, name, description, tags, examples, active, is_fallback,
              created_at, updated_at
            from workflow_definitions
            where tenant_id = $1 and project_id = $2 and active = true and is_fallback = true
            order by updated_at desc
            limit 1
            """,
            tenant_id,
            project_id,
        )
        if not row:
            return None
        return WorkflowDefinitionRecord(
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            workflow_id=row["workflow_id"],
            name=row["name"],
            description=row["description"],
            tags=[str(item) for item in (row["tags"] or [])],
            examples=[str(item) for item in (row["examples"] or [])],
            active=bool(row["active"]),
            is_fallback=bool(row["is_fallback"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def get_session_state(self, project_id: str, session_id: str, tenant_id: str) -> Optional[SessionStateRecord]:
        row = await self.pool.fetchrow(
            """
            select
              tenant_id, project_id, session_id, orchestrator_id, active_run_id, pending_disambiguation,
              pending_question, pending_options, disambiguation_turns, last_user_message_id,
              created_at, updated_at
            from orchestrator_session_state
            where tenant_id = $1 and project_id = $2 and session_id = $3
            """,
            tenant_id,
            project_id,
            session_id,
        )
        if not row:
            return None
        return SessionStateRecord(
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            session_id=row["session_id"],
            orchestrator_id=row["orchestrator_id"],
            active_run_id=row["active_run_id"],
            pending_disambiguation=bool(row["pending_disambiguation"]),
            pending_question=row["pending_question"],
            pending_options=[str(item) for item in _parse_list(row["pending_options"])],
            disambiguation_turns=int(row["disambiguation_turns"] or 0),
            last_user_message_id=row["last_user_message_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def save_session_state(self, state: SessionStateRecord) -> SessionStateRecord:
        await self.pool.execute(
            """
            insert into orchestrator_session_state (
              tenant_id, project_id, session_id, orchestrator_id, active_run_id, pending_disambiguation,
              pending_question, pending_options, disambiguation_turns, last_user_message_id
            )
            values ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)
            on conflict (tenant_id, project_id, session_id) do update
              set orchestrator_id = excluded.orchestrator_id,
                  active_run_id = excluded.active_run_id,
                  pending_disambiguation = excluded.pending_disambiguation,
                  pending_question = excluded.pending_question,
                  pending_options = excluded.pending_options,
                  disambiguation_turns = excluded.disambiguation_turns,
                  last_user_message_id = excluded.last_user_message_id,
                  updated_at = now()
            """,
            state.tenant_id,
            state.project_id,
            state.session_id,
            state.orchestrator_id,
            state.active_run_id,
            bool(state.pending_disambiguation),
            state.pending_question,
            _jsonb(state.pending_options or []),
            int(state.disambiguation_turns or 0),
            state.last_user_message_id,
        )
        loaded = await self.get_session_state(state.project_id, state.session_id, state.tenant_id)
        if loaded is None:
            raise RuntimeError("failed to save session state")
        return loaded

    async def append_stack_entry(
        self,
        project_id: str,
        session_id: str,
        tenant_id: str,
        run_id: str,
        transition_reason: str,
        from_run_id: Optional[str] = None,
    ) -> WorkflowStackEntryRecord:
        stack_index = await self.pool.fetchval(
            """
            select coalesce(max(stack_index), -1) + 1
            from workflow_stack_entries
            where tenant_id = $1 and project_id = $2 and session_id = $3
            """,
            tenant_id,
            project_id,
            session_id,
        )
        entry_id = _new_id("wstk")
        await self.pool.execute(
            """
            insert into workflow_stack_entries (
              id, tenant_id, project_id, session_id, run_id, stack_index, transition_reason, from_run_id
            )
            values ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            entry_id,
            tenant_id,
            project_id,
            session_id,
            run_id,
            int(stack_index),
            transition_reason,
            from_run_id,
        )
        rows = await self.list_stack(project_id, session_id, tenant_id)
        for row in rows:
            if row.id == entry_id:
                return row
        raise RuntimeError("failed to append stack entry")

    async def list_stack(self, project_id: str, session_id: str, tenant_id: str) -> List[WorkflowStackEntryRecord]:
        rows = await self.pool.fetch(
            """
            select id, tenant_id, project_id, session_id, run_id, stack_index, transition_reason, from_run_id, created_at
            from workflow_stack_entries
            where tenant_id = $1 and project_id = $2 and session_id = $3
            order by stack_index asc
            """,
            tenant_id,
            project_id,
            session_id,
        )
        return [
            WorkflowStackEntryRecord(
                id=row["id"],
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                session_id=row["session_id"],
                run_id=row["run_id"],
                stack_index=int(row["stack_index"]),
                transition_reason=row["transition_reason"],
                from_run_id=row["from_run_id"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def save_decision(self, decision: OrchestrationDecisionRecord) -> OrchestrationDecisionRecord:
        await self.pool.execute(
            """
            insert into orchestration_decisions (
              decision_id, tenant_id, project_id, orchestrator_id, session_id, message_id, mode, active_run_id,
              context_ref, candidates, chosen_action, chosen_workflow_id, confidence, latency_ms,
              model_id, error_code, created_at
            )
            values (
              $1, $2, $3, $4, $5, $6, $7, $8,
              $9::jsonb, $10::jsonb, $11, $12, $13, $14,
              $15, $16, $17
            )
            """,
            decision.decision_id,
            decision.tenant_id,
            decision.project_id,
            decision.orchestrator_id,
            decision.session_id,
            decision.message_id,
            decision.mode,
            decision.active_run_id,
            _jsonb(decision.context_ref or {}),
            _jsonb(decision.candidates or []),
            decision.chosen_action,
            decision.chosen_workflow_id,
            float(decision.confidence),
            int(decision.latency_ms),
            decision.model_id,
            decision.error_code,
            decision.created_at,
        )
        return decision

    async def list_recent_decisions(
        self,
        project_id: str,
        session_id: str,
        tenant_id: str,
        limit: int = 5,
    ) -> List[OrchestrationDecisionRecord]:
        rows = await self.pool.fetch(
            """
            select
              decision_id, tenant_id, project_id, orchestrator_id, session_id, message_id, mode, active_run_id,
              context_ref, candidates, chosen_action, chosen_workflow_id, confidence, latency_ms,
              model_id, error_code, created_at
            from orchestration_decisions
            where tenant_id = $1 and project_id = $2 and session_id = $3
            order by created_at desc
            limit $4
            """,
            tenant_id,
            project_id,
            session_id,
            limit,
        )
        return [
            OrchestrationDecisionRecord(
                decision_id=row["decision_id"],
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                orchestrator_id=row["orchestrator_id"],
                session_id=row["session_id"],
                message_id=row["message_id"],
                mode=row["mode"],
                active_run_id=row["active_run_id"],
                context_ref=_parse_dict(row["context_ref"]),
                candidates=_parse_list(row["candidates"]),
                chosen_action=row["chosen_action"],
                chosen_workflow_id=row["chosen_workflow_id"],
                confidence=float(row["confidence"] or 0),
                latency_ms=int(row["latency_ms"] or 0),
                model_id=row["model_id"],
                error_code=row["error_code"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def close(self) -> None:
        return None


async def create_orchestration_store(workflow_store: Any | None = None) -> OrchestrationStore:
    pool = getattr(workflow_store, "pool", None)
    if isinstance(pool, asyncpg.Pool):
        return PostgresOrchestrationStore(pool=pool)
    return InMemoryOrchestrationStore()
