-- Add human-readable project_name to project registry scope.

alter table if exists projects
  add column if not exists project_name text;

update projects
set project_name = coalesce(
  nullif(
    btrim(
      regexp_replace(
        initcap(
          regexp_replace(
            regexp_replace(project_id, '^(proj|project)[_-]+', '', 'i'),
            '[_-]+',
            ' ',
            'g'
          )
        ),
        '\\s+',
        ' ',
        'g'
      )
    ),
    ''
  ),
  project_id
)
where coalesce(btrim(project_name), '') = '';

alter table if exists projects
  alter column project_name set not null;

do $$
begin
  if to_regclass('projects') is not null and not exists (
    select 1
    from pg_constraint
    where conname = 'chk_projects_project_name_not_blank'
  ) then
    alter table projects
      add constraint chk_projects_project_name_not_blank
      check (char_length(btrim(project_name)) > 0);
  end if;
end
$$;
