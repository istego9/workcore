# Development Workflow

## Purpose
This document defines merge gates and execution order for WorkCore changes.

## Change flow
1. Classify task type (A-G from `AGENTS.md`).
2. For A-E tasks, update specs first:
   - `docs/api/openapi.yaml`
   - `docs/api/schemas/*.json`
   - `db/migrations/*.sql`
   - `docs/architecture/*.md` or `docs/adr/*.md` when behavior changes
3. Implement code changes.
4. Add/update tests.
5. Run required checks.
6. Update docs/runbooks and prepare PR summary.

## Mandatory action items for specification tasks
Use this checklist in PR descriptions for A-E changes:
1. Goal and scope
2. Spec files changed
3. Compatibility strategy (additive/breaking)
4. Implementation files changed
5. Tests added/updated
6. Observability/security impact
7. Rollout/rollback plan
8. Open TODOs/questions

## Required checks before merge
- `./scripts/archctl_validate.sh`
- `./.venv/bin/python -m pytest apps/orchestrator/tests`
- `cd apps/builder && npm run test:unit`

When applicable:
- `cd apps/builder && npm run test:e2e`
- `./scripts/e2e_suite.sh` (full local E2E: backend + chatkit + builder)
- `./scripts/dev_check.sh`
- `USE_PROXY=1 RUN_E2E=1 ./scripts/dev_check.sh` (domain mode + full E2E)

If a required check cannot be run, the PR must include:
- exact blocking reason
- risk statement
- follow-up validation plan

## PR hygiene
- Keep changes small and focused.
- Separate spec updates from implementation when feasible.
- Include a verification section with exact commands and outcomes.
- Do not claim validations that were not executed.
