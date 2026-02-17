-- Project orchestrators + intent routing persistence (MVP).

alter table if exists runs
  add column if not exists project_id text;

alter table if exists runs
  add column if not exists session_id text;

alter table if exists runs
  add column if not exists resolved_version text;

alter table if exists runs
  add column if not exists cancellable boolean not null default true;

alter table if exists runs
  add column if not exists commit_point_reached boolean;

create index if not exists idx_runs_project_session
  on runs (project_id, session_id, created_at desc);

create table if not exists projects (
  project_id text primary key,
  tenant_id text not null,
  default_orchestrator_id text,
  settings jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_projects_tenant
  on projects (tenant_id);

create table if not exists orchestrator_configs (
  project_id text not null references projects(project_id) on delete cascade,
  orchestrator_id text not null,
  name text not null,
  routing_policy jsonb not null default '{}'::jsonb,
  fallback_workflow_id text,
  prompt_profile text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (project_id, orchestrator_id)
);

create index if not exists idx_orchestrator_configs_project
  on orchestrator_configs (project_id);

create table if not exists workflow_definitions (
  project_id text not null references projects(project_id) on delete cascade,
  workflow_id text not null references workflows(id) on delete cascade,
  name text not null,
  description text not null,
  tags text[] not null default '{}',
  examples text[] not null default '{}',
  active boolean not null default true,
  is_fallback boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (project_id, workflow_id)
);

create index if not exists idx_workflow_definitions_project_active
  on workflow_definitions (project_id, active);

create index if not exists idx_workflow_definitions_project_fallback
  on workflow_definitions (project_id, is_fallback);

create table if not exists orchestration_decisions (
  decision_id text primary key,
  project_id text not null references projects(project_id) on delete cascade,
  orchestrator_id text,
  session_id text not null,
  message_id text not null,
  mode text not null,
  active_run_id text,
  context_ref jsonb not null default '{}'::jsonb,
  candidates jsonb not null default '[]'::jsonb,
  chosen_action text not null,
  chosen_workflow_id text,
  confidence double precision not null default 0,
  latency_ms integer not null default 0,
  model_id text,
  error_code text,
  created_at timestamptz not null default now(),
  constraint chk_orchestration_decisions_mode check (mode in ('direct', 'orchestrated')),
  constraint chk_orchestration_decisions_action check (
    chosen_action in (
      'RESUME_CURRENT',
      'START_WORKFLOW',
      'SWITCH_WORKFLOW',
      'DISAMBIGUATE',
      'FALLBACK',
      'CANCEL',
      'OPERATOR'
    )
  )
);

create index if not exists idx_orchestration_decisions_project_session
  on orchestration_decisions (project_id, session_id, created_at desc);

create table if not exists workflow_stack_entries (
  id text primary key,
  project_id text not null references projects(project_id) on delete cascade,
  session_id text not null,
  run_id text not null,
  stack_index integer not null,
  transition_reason text not null,
  from_run_id text,
  created_at timestamptz not null default now()
);

create unique index if not exists uq_workflow_stack_entries_session_index
  on workflow_stack_entries (project_id, session_id, stack_index);

create index if not exists idx_workflow_stack_entries_session
  on workflow_stack_entries (project_id, session_id, created_at desc);

create table if not exists orchestrator_session_state (
  project_id text not null references projects(project_id) on delete cascade,
  session_id text not null,
  orchestrator_id text,
  active_run_id text,
  pending_disambiguation boolean not null default false,
  pending_question text,
  pending_options jsonb not null default '[]'::jsonb,
  disambiguation_turns integer not null default 0,
  last_user_message_id text,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  primary key (project_id, session_id)
);

create index if not exists idx_orchestrator_session_state_active
  on orchestrator_session_state (project_id, active_run_id);
