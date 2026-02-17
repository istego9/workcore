-- Enforce strict multi-tenant scoping for ChatKit persistence tables.

alter table if exists chatkit_threads
  add column if not exists tenant_id text;

update chatkit_threads
set tenant_id = 'local'
where tenant_id is null;

alter table if exists chatkit_threads
  alter column tenant_id set not null;

alter table if exists chatkit_items
  add column if not exists tenant_id text;

update chatkit_items i
set tenant_id = t.tenant_id
from chatkit_threads t
where i.thread_id = t.id
  and i.tenant_id is null;

update chatkit_items
set tenant_id = 'local'
where tenant_id is null;

alter table if exists chatkit_items
  alter column tenant_id set not null;

alter table if exists chatkit_attachments
  add column if not exists tenant_id text;

update chatkit_attachments a
set tenant_id = t.tenant_id
from chatkit_threads t
where a.thread_id = t.id
  and a.tenant_id is null;

update chatkit_attachments
set tenant_id = 'local'
where tenant_id is null;

alter table if exists chatkit_attachments
  alter column tenant_id set not null;

do $$
declare
  threads_pk text[];
  items_pk text[];
  attachments_pk text[];
begin
  if to_regclass('chatkit_threads') is not null then
    select array_agg(att.attname order by k.ordinality)
    into threads_pk
    from pg_constraint c
    join unnest(c.conkey) with ordinality as k(attnum, ordinality) on true
    join pg_attribute att
      on att.attrelid = c.conrelid
     and att.attnum = k.attnum
    where c.conrelid = 'chatkit_threads'::regclass
      and c.contype = 'p';

    if threads_pk = array['id'] then
      alter table if exists chatkit_items
        drop constraint if exists chatkit_items_thread_id_fkey;
      alter table if exists chatkit_attachments
        drop constraint if exists chatkit_attachments_thread_id_fkey;
      alter table if exists chatkit_items
        drop constraint if exists fk_chatkit_items_thread_scope;
      alter table if exists chatkit_attachments
        drop constraint if exists fk_chatkit_attachments_thread_scope;
      alter table chatkit_threads
        drop constraint if exists chatkit_threads_pkey;
      alter table chatkit_threads
        add constraint chatkit_threads_pkey primary key (tenant_id, id);
    elsif threads_pk is null then
      alter table chatkit_threads
        add constraint chatkit_threads_pkey primary key (tenant_id, id);
    end if;
  end if;

  if to_regclass('chatkit_items') is not null then
    select array_agg(att.attname order by k.ordinality)
    into items_pk
    from pg_constraint c
    join unnest(c.conkey) with ordinality as k(attnum, ordinality) on true
    join pg_attribute att
      on att.attrelid = c.conrelid
     and att.attnum = k.attnum
    where c.conrelid = 'chatkit_items'::regclass
      and c.contype = 'p';

    if items_pk = array['id'] then
      alter table chatkit_items
        drop constraint if exists chatkit_items_pkey;
      alter table chatkit_items
        add constraint chatkit_items_pkey primary key (tenant_id, id);
    elsif items_pk is null then
      alter table chatkit_items
        add constraint chatkit_items_pkey primary key (tenant_id, id);
    end if;
  end if;

  if to_regclass('chatkit_attachments') is not null then
    select array_agg(att.attname order by k.ordinality)
    into attachments_pk
    from pg_constraint c
    join unnest(c.conkey) with ordinality as k(attnum, ordinality) on true
    join pg_attribute att
      on att.attrelid = c.conrelid
     and att.attnum = k.attnum
    where c.conrelid = 'chatkit_attachments'::regclass
      and c.contype = 'p';

    if attachments_pk = array['id'] then
      alter table chatkit_attachments
        drop constraint if exists chatkit_attachments_pkey;
      alter table chatkit_attachments
        add constraint chatkit_attachments_pkey primary key (tenant_id, id);
    elsif attachments_pk is null then
      alter table chatkit_attachments
        add constraint chatkit_attachments_pkey primary key (tenant_id, id);
    end if;
  end if;
end
$$;

do $$
begin
  if to_regclass('chatkit_items') is not null and not exists (
    select 1 from pg_constraint where conname = 'fk_chatkit_items_thread_scope'
  ) then
    alter table chatkit_items
      add constraint fk_chatkit_items_thread_scope
      foreign key (tenant_id, thread_id)
      references chatkit_threads(tenant_id, id)
      on delete cascade;
  end if;

  if to_regclass('chatkit_attachments') is not null and not exists (
    select 1 from pg_constraint where conname = 'fk_chatkit_attachments_thread_scope'
  ) then
    alter table chatkit_attachments
      add constraint fk_chatkit_attachments_thread_scope
      foreign key (tenant_id, thread_id)
      references chatkit_threads(tenant_id, id)
      on delete set null;
  end if;
end
$$;

create index if not exists idx_chatkit_threads_tenant_seq
  on chatkit_threads (tenant_id, seq);

create index if not exists idx_chatkit_items_tenant_thread_seq
  on chatkit_items (tenant_id, thread_id, seq);

create index if not exists idx_chatkit_attachments_tenant_thread
  on chatkit_attachments (tenant_id, thread_id);
