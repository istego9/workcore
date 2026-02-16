# Project Registry Bootstrap API - Spec-First Action Items

Date: 2026-02-16
Status: COMPLETED
Task classification: B (API contract change), E (external integration behavior change)

## 1) Goal and scope
- Add public project-registry bootstrap APIs so orchestrator routing can be bootstrapped without DB-side seed scripts.
- Provide explicit public APIs for:
  - project creation/bootstrap in orchestrator registry,
  - project orchestrator configuration binding,
  - project workflow definition registration.
- Add an optional atomic bootstrap endpoint that can bind project + orchestrator + workflow definitions in one request.

Out of scope:
- DB schema changes or new migrations (use existing `projects`, `orchestrator_configs`, `workflow_definitions` tables).
- Changes to runtime routing decision semantics.

## 2) Spec files to update (exact paths)
- `docs/api/openapi.yaml`
- `docs/api/reference.md`
- `CHANGELOG.md`

No changes planned:
- `docs/api/schemas/*.json`
- `db/migrations/*.sql`
- `docs/architecture/data-model.md`

## 3) Compatibility strategy (additive vs breaking)
- Additive-only API changes:
  - New bootstrap/config endpoints under `/projects/{project_id}/...`.
  - Existing `/workflows*`, `/runs*`, `/orchestrator/messages` behavior remains backward compatible.
- Error envelope remains unchanged (`error.code`, `error.message`, optional `details`, `correlation_id`).

## 4) Implementation files
- `apps/orchestrator/api/app.py`
- `apps/orchestrator/api/serializers.py`

## 5) Tests (unit/integration/contract/e2e)
- Update/add API tests:
  - `apps/orchestrator/tests/test_api.py`
- Validate API/docs consistency:
  - `./scripts/archctl_validate.sh`
- Validate orchestrator API test coverage:
  - `./.venv/bin/python -m pytest apps/orchestrator/tests/test_api.py`

## 6) Observability/security impacts
- New endpoints reuse current auth and correlation model.
- Responses include correlation IDs through existing API envelope logic.
- No new sensitive payload logging should be introduced.

## 7) Rollout/rollback notes
- Rollout:
  - Deploy API with new `/projects/{project_id}/...` endpoints.
  - Validate bootstrap flow end-to-end via curl in target environment.
- Rollback:
  - Revert endpoint additions without DB rollback requirements (schema unchanged).

## 8) Outstanding TODOs/questions
- Confirm whether to expose list/read endpoints for project registry entities in a follow-up (not required for bootstrap write path).

## Validation results
- `./scripts/archctl_validate.sh` -> PASS
- `./.venv/bin/python -m pytest apps/orchestrator/tests/test_api.py -q` -> PASS
- `./.venv/bin/python -m pytest apps/orchestrator/tests -q` -> PARTIAL (unrelated existing failures in `apps/orchestrator/tests/test_webhooks.py` due missing `X-Project-Id` in those tests)
