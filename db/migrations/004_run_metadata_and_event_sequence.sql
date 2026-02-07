-- API transparency additions:
-- 1) Persist run request metadata for correlation and tenant traceability.
-- 2) Reserve an explicit per-run event sequence column for durable event stores.

alter table if exists runs
  add column if not exists metadata jsonb not null default '{}'::jsonb;

alter table if exists events
  add column if not exists sequence bigint;

create unique index if not exists uq_events_run_sequence
  on events (run_id, sequence)
  where sequence is not null;
