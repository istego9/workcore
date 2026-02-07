---
name: schema-migrations-postgres
description: >
  Safe Postgres schema evolution for WorkCore. Use when adding/changing tables, columns,
  indexes, constraints, or run/event persistence fields.
---

# Schema Migrations (Postgres)

## Goal
Make DB changes reproducible, idempotent, and backward-safe.

## Required files
- SQL migration in `db/migrations/*.sql` (ordered)
- Data model docs update in `docs/architecture/data-model.md` if model changes

## Workflow
1) Create additive migration first (avoid destructive changes by default).
2) Use `if exists` / `if not exists` patterns for idempotency.
3) Update docs for changed tables/columns/indexes.
4) Apply locally with `./.venv/bin/python scripts/migrate.py`.
5) Add/adjust tests covering read/write behavior.

## Validation
- Migration applies cleanly on an existing DB.
- Migration applies cleanly on a fresh DB.
- Runtime/API tests pass for affected flows.

## Guardrails
- No destructive migration without rollout and backfill plan.
- No schema changes without corresponding docs/tests updates.
