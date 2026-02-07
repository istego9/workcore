-- Persist runtime-specific run state required for resume/rerun across restarts.

alter table if exists runs
  add column if not exists mode text not null default 'live';

alter table if exists runs
  add column if not exists node_outputs jsonb not null default '{}'::jsonb;

alter table if exists runs
  add column if not exists branch_selection jsonb not null default '{}'::jsonb;

alter table if exists runs
  add column if not exists loop_state jsonb not null default '{}'::jsonb;

alter table if exists runs
  add column if not exists skipped_nodes jsonb not null default '[]'::jsonb;

alter table if exists node_runs
  add column if not exists trace_id text;

alter table if exists node_runs
  add column if not exists usage jsonb;

alter table if exists interrupts
  add column if not exists state_target text;
