-- Unified context persistence for orchestrator/session/thread scope (P0).

create table if not exists orchestrator_context (
  tenant_id text not null,
  project_id text not null default '',
  scope_type text not null,
  scope_id text not null,
  key text not null,
  value jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (tenant_id, project_id, scope_type, scope_id, key),
  constraint chk_orchestrator_context_scope_type check (scope_type in ('session', 'thread'))
);

create index if not exists idx_orchestrator_context_tenant_project_scope
  on orchestrator_context (tenant_id, project_id, scope_type, scope_id, updated_at desc);
