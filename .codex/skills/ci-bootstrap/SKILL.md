---
name: ci-bootstrap
description: >
  Bootstrap CI merge gates for WorkCore. Use when CI is missing/incomplete or when
  adding required checks for API/runtime/builder changes.
---

# CI Bootstrap

## Goal
Every PR runs deterministic checks that protect contracts and runtime behavior.

## Minimum gates
1) `./scripts/archctl_validate.sh`
2) Orchestrator tests: `./.venv/bin/python -m pytest apps/orchestrator/tests`
3) Builder unit tests: `cd apps/builder && npm run test:unit`
4) Optional builder e2e on demand or path filter

## Workflow
1) Add CI workflow file (`.github/workflows/ci.yml`).
2) Use path filters to avoid unnecessary heavy jobs.
3) Fail fast on contract/schema failures before long jobs.
4) Document required checks in `docs/DEV_WORKFLOW.md`.

## Guardrails
- Do not add fake passing jobs.
- Keep checks runnable locally with the same commands.
