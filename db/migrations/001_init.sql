-- Initial schema for MVP (Phase 1)

create table if not exists workflows (
  id text primary key,
  tenant_id text not null,
  name text not null,
  description text,
  draft jsonb not null default '{}'::jsonb,
  active_version_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_workflows_tenant on workflows (tenant_id);

create table if not exists workflow_versions (
  id text primary key,
  workflow_id text not null references workflows(id) on delete cascade,
  tenant_id text not null,
  version_number int not null,
  hash text not null,
  content jsonb not null,
  created_at timestamptz not null default now()
);

create unique index if not exists uq_workflow_versions_workflow_version
  on workflow_versions (workflow_id, version_number);
create index if not exists idx_workflow_versions_tenant on workflow_versions (tenant_id);

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'fk_workflows_active_version'
  ) then
    alter table workflows
      add constraint fk_workflows_active_version
      foreign key (active_version_id) references workflow_versions(id);
  end if;
end
$$;

create table if not exists runs (
  id text primary key,
  workflow_id text not null references workflows(id) on delete cascade,
  version_id text not null references workflow_versions(id),
  tenant_id text not null,
  status text not null,
  inputs jsonb not null default '{}'::jsonb,
  state jsonb not null default '{}'::jsonb,
  outputs jsonb,
  correlation_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  constraint chk_runs_status check (status in (
    'RUNNING','WAITING_FOR_INPUT','COMPLETED','FAILED','CANCELLED'
  ))
);

create index if not exists idx_runs_workflow_status
  on runs (workflow_id, status, created_at);
create index if not exists idx_runs_tenant on runs (tenant_id);

create table if not exists node_runs (
  id text primary key,
  run_id text not null references runs(id) on delete cascade,
  node_id text not null,
  status text not null,
  attempt int not null default 1,
  output jsonb,
  last_error jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  constraint chk_node_runs_status check (status in (
    'TO_DO','IN_PROGRESS','RESOLVED','ERROR','CANCELLED'
  ))
);

create unique index if not exists uq_node_runs_run_node_attempt
  on node_runs (run_id, node_id, attempt);
create index if not exists idx_node_runs_run_status
  on node_runs (run_id, status);

create table if not exists interrupts (
  id text primary key,
  run_id text not null references runs(id) on delete cascade,
  node_id text not null,
  tenant_id text not null,
  type text not null,
  status text not null,
  prompt text not null,
  input_schema jsonb,
  allow_file_upload boolean not null default false,
  input jsonb,
  files jsonb,
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  resolved_at timestamptz,
  constraint chk_interrupts_status check (status in (
    'OPEN','RESOLVED','CANCELLED','EXPIRED'
  ))
);

create index if not exists idx_interrupts_run on interrupts (run_id);
create index if not exists idx_interrupts_tenant on interrupts (tenant_id);

create table if not exists files (
  id text primary key,
  tenant_id text not null,
  object_key text not null,
  content_type text,
  size_bytes bigint,
  sha256 text,
  created_at timestamptz not null default now()
);

create index if not exists idx_files_tenant on files (tenant_id);

create table if not exists events (
  id text primary key,
  run_id text not null references runs(id) on delete cascade,
  workflow_id text not null,
  version_id text not null,
  node_id text,
  tenant_id text not null,
  type text not null,
  payload jsonb not null,
  correlation_id text,
  created_at timestamptz not null default now()
);

create index if not exists idx_events_run_created
  on events (run_id, created_at);
create index if not exists idx_events_tenant
  on events (tenant_id);

create table if not exists webhook_subscriptions (
  id text primary key,
  tenant_id text not null,
  url text not null,
  event_types text[] not null,
  secret_ref text not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_webhook_subscriptions_tenant
  on webhook_subscriptions (tenant_id);

create table if not exists webhook_deliveries (
  id text primary key,
  subscription_id text not null references webhook_subscriptions(id) on delete cascade,
  event_id text,
  event_type text not null,
  payload jsonb not null,
  status text not null,
  attempt_count int not null default 0,
  last_error text,
  next_retry_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint chk_webhook_delivery_status check (status in (
    'PENDING','SUCCESS','FAILED'
  ))
);

create index if not exists idx_webhook_deliveries_status_retry
  on webhook_deliveries (status, next_retry_at);

create table if not exists webhook_inbound_keys (
  id text primary key,
  tenant_id text not null,
  integration_key text not null unique,
  secret_ref text not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_webhook_inbound_keys_tenant
  on webhook_inbound_keys (tenant_id);

create table if not exists idempotency_keys (
  id text primary key,
  tenant_id text not null,
  idempotency_key text not null,
  scope text not null,
  request_hash text not null,
  response_body jsonb,
  status text not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  constraint chk_idempotency_status check (status in (
    'IN_PROGRESS','COMPLETED','FAILED'
  ))
);

create unique index if not exists uq_idempotency_keys_tenant_scope_key
  on idempotency_keys (tenant_id, idempotency_key, scope);
create index if not exists idx_idempotency_keys_expires_at
  on idempotency_keys (expires_at);
