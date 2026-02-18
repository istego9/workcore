-- Reliability hardening:
-- 1) capability registry with versioned contracts
-- 2) immutable run ledger
-- 3) atomic handoff package persistence with replay metadata

create table if not exists capabilities (
  id text primary key,
  tenant_id text not null,
  capability_id text not null,
  version text not null,
  node_type text not null,
  contract jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create unique index if not exists uq_capabilities_tenant_id_version
  on capabilities (tenant_id, capability_id, version);

create index if not exists idx_capabilities_tenant_capability_created
  on capabilities (tenant_id, capability_id, created_at desc);

create table if not exists run_ledger (
  id text primary key,
  tenant_id text not null,
  run_id text not null references runs(id) on delete cascade,
  workflow_id text not null,
  version_id text not null,
  step_id text,
  capability_id text,
  capability_version text,
  status text not null,
  event_type text not null,
  decision jsonb,
  artifacts jsonb not null default '[]'::jsonb,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_run_ledger_tenant_run_created
  on run_ledger (tenant_id, run_id, created_at desc);

create index if not exists idx_run_ledger_tenant_workflow_created
  on run_ledger (tenant_id, workflow_id, created_at desc);

create table if not exists workflow_handoffs (
  id text primary key,
  tenant_id text not null,
  workflow_id text not null,
  version_id text,
  context jsonb not null default '{}'::jsonb,
  constraints jsonb not null default '{}'::jsonb,
  expected_result jsonb not null default '{}'::jsonb,
  acceptance_checks jsonb not null default '[]'::jsonb,
  replay_mode text not null default 'none',
  idempotency_key text,
  run_id text,
  status text not null default 'RECEIVED',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint chk_workflow_handoffs_replay_mode check (replay_mode in ('none', 'deterministic')),
  constraint chk_workflow_handoffs_status check (status in ('RECEIVED', 'STARTED', 'REPLAYED', 'FAILED'))
);

create unique index if not exists uq_workflow_handoffs_tenant_idempotency
  on workflow_handoffs (tenant_id, idempotency_key)
  where idempotency_key is not null;

create index if not exists idx_workflow_handoffs_tenant_workflow_created
  on workflow_handoffs (tenant_id, workflow_id, created_at desc);

