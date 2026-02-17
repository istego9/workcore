-- Enforce tenant-scoped project orchestration keys.
-- project_id is unique only within tenant_id.

alter table if exists projects
  alter column tenant_id set default 'local';

update projects
set tenant_id = 'local'
where tenant_id is null;

alter table if exists projects
  alter column tenant_id set not null;

alter table if exists orchestrator_configs
  add column if not exists tenant_id text;

update orchestrator_configs oc
set tenant_id = p.tenant_id
from projects p
where oc.project_id = p.project_id
  and oc.tenant_id is null;

update orchestrator_configs
set tenant_id = 'local'
where tenant_id is null;

alter table if exists orchestrator_configs
  alter column tenant_id set not null;

alter table if exists workflow_definitions
  add column if not exists tenant_id text;

update workflow_definitions wd
set tenant_id = p.tenant_id
from projects p
where wd.project_id = p.project_id
  and wd.tenant_id is null;

update workflow_definitions
set tenant_id = 'local'
where tenant_id is null;

alter table if exists workflow_definitions
  alter column tenant_id set not null;

alter table if exists orchestrator_session_state
  add column if not exists tenant_id text;

update orchestrator_session_state oss
set tenant_id = p.tenant_id
from projects p
where oss.project_id = p.project_id
  and oss.tenant_id is null;

update orchestrator_session_state
set tenant_id = 'local'
where tenant_id is null;

alter table if exists orchestrator_session_state
  alter column tenant_id set not null;

alter table if exists workflow_stack_entries
  add column if not exists tenant_id text;

update workflow_stack_entries wse
set tenant_id = p.tenant_id
from projects p
where wse.project_id = p.project_id
  and wse.tenant_id is null;

update workflow_stack_entries
set tenant_id = 'local'
where tenant_id is null;

alter table if exists workflow_stack_entries
  alter column tenant_id set not null;

alter table if exists orchestration_decisions
  add column if not exists tenant_id text;

update orchestration_decisions od
set tenant_id = p.tenant_id
from projects p
where od.project_id = p.project_id
  and od.tenant_id is null;

update orchestration_decisions
set tenant_id = 'local'
where tenant_id is null;

alter table if exists orchestration_decisions
  alter column tenant_id set not null;

do $$
declare
  projects_pk text[];
  cfg_pk text[];
  defs_pk text[];
  session_pk text[];
begin
  if to_regclass('projects') is not null then
    select array_agg(att.attname order by k.ordinality)
    into projects_pk
    from pg_constraint c
    join unnest(c.conkey) with ordinality as k(attnum, ordinality) on true
    join pg_attribute att
      on att.attrelid = c.conrelid
     and att.attnum = k.attnum
    where c.conrelid = 'projects'::regclass
      and c.contype = 'p';

    if projects_pk = array['project_id'] then
      alter table if exists orchestrator_configs
        drop constraint if exists orchestrator_configs_project_id_fkey;
      alter table if exists workflow_definitions
        drop constraint if exists workflow_definitions_project_id_fkey;
      alter table if exists workflow_stack_entries
        drop constraint if exists workflow_stack_entries_project_id_fkey;
      alter table if exists orchestration_decisions
        drop constraint if exists orchestration_decisions_project_id_fkey;
      alter table if exists orchestrator_session_state
        drop constraint if exists orchestrator_session_state_project_id_fkey;
      alter table projects
        drop constraint if exists projects_pkey;
      alter table projects
        add constraint projects_pkey primary key (tenant_id, project_id);
    elsif projects_pk is null then
      alter table projects
        add constraint projects_pkey primary key (tenant_id, project_id);
    end if;
  end if;

  if to_regclass('orchestrator_configs') is not null then
    select array_agg(att.attname order by k.ordinality)
    into cfg_pk
    from pg_constraint c
    join unnest(c.conkey) with ordinality as k(attnum, ordinality) on true
    join pg_attribute att
      on att.attrelid = c.conrelid
     and att.attnum = k.attnum
    where c.conrelid = 'orchestrator_configs'::regclass
      and c.contype = 'p';

    if cfg_pk = array['project_id', 'orchestrator_id'] then
      alter table orchestrator_configs
        drop constraint if exists orchestrator_configs_pkey;
      alter table orchestrator_configs
        add constraint orchestrator_configs_pkey primary key (tenant_id, project_id, orchestrator_id);
    elsif cfg_pk is null then
      alter table orchestrator_configs
        add constraint orchestrator_configs_pkey primary key (tenant_id, project_id, orchestrator_id);
    end if;
  end if;

  if to_regclass('workflow_definitions') is not null then
    select array_agg(att.attname order by k.ordinality)
    into defs_pk
    from pg_constraint c
    join unnest(c.conkey) with ordinality as k(attnum, ordinality) on true
    join pg_attribute att
      on att.attrelid = c.conrelid
     and att.attnum = k.attnum
    where c.conrelid = 'workflow_definitions'::regclass
      and c.contype = 'p';

    if defs_pk = array['project_id', 'workflow_id'] then
      alter table workflow_definitions
        drop constraint if exists workflow_definitions_pkey;
      alter table workflow_definitions
        add constraint workflow_definitions_pkey primary key (tenant_id, project_id, workflow_id);
    elsif defs_pk is null then
      alter table workflow_definitions
        add constraint workflow_definitions_pkey primary key (tenant_id, project_id, workflow_id);
    end if;
  end if;

  if to_regclass('orchestrator_session_state') is not null then
    select array_agg(att.attname order by k.ordinality)
    into session_pk
    from pg_constraint c
    join unnest(c.conkey) with ordinality as k(attnum, ordinality) on true
    join pg_attribute att
      on att.attrelid = c.conrelid
     and att.attnum = k.attnum
    where c.conrelid = 'orchestrator_session_state'::regclass
      and c.contype = 'p';

    if session_pk = array['project_id', 'session_id'] then
      alter table orchestrator_session_state
        drop constraint if exists orchestrator_session_state_pkey;
      alter table orchestrator_session_state
        add constraint orchestrator_session_state_pkey primary key (tenant_id, project_id, session_id);
    elsif session_pk is null then
      alter table orchestrator_session_state
        add constraint orchestrator_session_state_pkey primary key (tenant_id, project_id, session_id);
    end if;
  end if;
end
$$;

do $$
begin
  if to_regclass('orchestrator_configs') is not null and not exists (
    select 1 from pg_constraint where conname = 'fk_orchestrator_configs_project_scope'
  ) then
    alter table orchestrator_configs
      add constraint fk_orchestrator_configs_project_scope
      foreign key (tenant_id, project_id)
      references projects(tenant_id, project_id)
      on delete cascade;
  end if;

  if to_regclass('workflow_definitions') is not null and not exists (
    select 1 from pg_constraint where conname = 'fk_workflow_definitions_project_scope'
  ) then
    alter table workflow_definitions
      add constraint fk_workflow_definitions_project_scope
      foreign key (tenant_id, project_id)
      references projects(tenant_id, project_id)
      on delete cascade;
  end if;

  if to_regclass('orchestrator_session_state') is not null and not exists (
    select 1 from pg_constraint where conname = 'fk_orchestrator_session_state_project_scope'
  ) then
    alter table orchestrator_session_state
      add constraint fk_orchestrator_session_state_project_scope
      foreign key (tenant_id, project_id)
      references projects(tenant_id, project_id)
      on delete cascade;
  end if;

  if to_regclass('workflow_stack_entries') is not null and not exists (
    select 1 from pg_constraint where conname = 'fk_workflow_stack_entries_project_scope'
  ) then
    alter table workflow_stack_entries
      add constraint fk_workflow_stack_entries_project_scope
      foreign key (tenant_id, project_id)
      references projects(tenant_id, project_id)
      on delete cascade;
  end if;

  if to_regclass('orchestration_decisions') is not null and not exists (
    select 1 from pg_constraint where conname = 'fk_orchestration_decisions_project_scope'
  ) then
    alter table orchestration_decisions
      add constraint fk_orchestration_decisions_project_scope
      foreign key (tenant_id, project_id)
      references projects(tenant_id, project_id)
      on delete cascade;
  end if;
end
$$;

do $$
declare
  idxdef text;
begin
  if to_regclass('uq_workflow_stack_entries_session_index') is not null then
    select pg_get_indexdef(to_regclass('uq_workflow_stack_entries_session_index'))
    into idxdef;
    if idxdef is not null
      and idxdef like '%(project_id, session_id, stack_index)%'
      and idxdef not like '%tenant_id%'
    then
      drop index if exists uq_workflow_stack_entries_session_index;
    end if;
  end if;
end
$$;

create unique index if not exists uq_workflow_stack_entries_session_index
  on workflow_stack_entries (tenant_id, project_id, session_id, stack_index);

create index if not exists idx_projects_tenant_project
  on projects (tenant_id, project_id);

create index if not exists idx_orchestrator_configs_tenant_project
  on orchestrator_configs (tenant_id, project_id);

create index if not exists idx_workflow_definitions_tenant_project_active
  on workflow_definitions (tenant_id, project_id, active);

create index if not exists idx_orchestrator_session_state_tenant_active
  on orchestrator_session_state (tenant_id, project_id, active_run_id);

create index if not exists idx_workflow_stack_entries_tenant_session
  on workflow_stack_entries (tenant_id, project_id, session_id, created_at desc);

create index if not exists idx_orchestration_decisions_tenant_session
  on orchestration_decisions (tenant_id, project_id, session_id, created_at desc);
