-- Scope workflow authoring entities by project identifier.

alter table if exists workflows
  add column if not exists project_id text;

create index if not exists idx_workflows_tenant_project
  on workflows (tenant_id, project_id, updated_at desc);
