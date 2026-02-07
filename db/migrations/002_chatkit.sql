-- ChatKit persistence (Phase 6)

create table if not exists chatkit_threads (
  id text primary key,
  seq bigserial not null,
  title text,
  status jsonb not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null,
  updated_at timestamptz not null default now()
);

create index if not exists idx_chatkit_threads_seq
  on chatkit_threads (seq);

create table if not exists chatkit_items (
  id text primary key,
  thread_id text not null references chatkit_threads(id) on delete cascade,
  seq bigserial not null,
  type text not null,
  item jsonb not null,
  created_at timestamptz not null
);

create index if not exists idx_chatkit_items_thread_seq
  on chatkit_items (thread_id, seq);

create table if not exists chatkit_attachments (
  id text primary key,
  thread_id text references chatkit_threads(id) on delete set null,
  attachment jsonb not null,
  created_at timestamptz not null
);

create index if not exists idx_chatkit_attachments_thread
  on chatkit_attachments (thread_id);
