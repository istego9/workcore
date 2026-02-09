# WorkCore Security Hardening - Spec-First Action Items

Date: 2026-02-07
Status: IN_PROGRESS
Task classification: E (external integration behavior change)

## 1) Goal and scope
- Standardize secure local WorkCore startup for the dev team.
- Require bearer auth and inbound webhook signature secret in the default WorkCore runtime profile.
- Narrow CORS to explicit, known WorkCore/HQ21 origins.

Out of scope:
- New auth frameworks or identity providers.
- DB schema changes.

## 2) Spec files to update (exact paths)
- `docs/api/openapi.yaml`
- `docs/api/reference.md`
- `docs/api/conventions.md`
- `docs/deploy/docker-workcore-build.md`

No changes planned:
- `docs/api/schemas/*.json`
- `db/migrations/*.sql`

## 3) Compatibility strategy (additive vs breaking)
- Behavior hardening with explicit startup guardrails.
- Existing API routes and payload schemas remain unchanged.
- Breaking impact is limited to environments that relied on empty auth/secret values.

## 4) Implementation files
- `apps/orchestrator/api/service.py`
- `apps/orchestrator/api/app.py`
- `apps/orchestrator/chatkit/service.py`
- `.env.docker`
- `.env.docker.example`
- `docker-compose.workcore.yml`
- `scripts/docker_up.sh`

## 5) Tests (unit/integration/contract/e2e)
- `./scripts/archctl_validate.sh`
- `./.venv/bin/python -m pytest apps/orchestrator/tests/test_api.py`
- `./.venv/bin/python -m pytest apps/orchestrator/tests/test_webhooks.py`

## 6) Observability/security impacts
- `Authorization` and webhook signature verification are on by default for WorkCore runtime profile.
- Secrets must not be logged; error payloads remain generic.
- CORS preflight is constrained to explicit allowlist origins.

## 7) Rollout/rollback notes
- Rollout:
  - Update `.env.docker` values and restart WorkCore services.
  - Update clients and webhook senders to include bearer and signature headers.
- Rollback:
  - Use explicit insecure override env only for temporary local troubleshooting.
  - Revert to previous env/docs if integration blockers appear.

## 8) Outstanding TODOs/questions
- TODO: Decide whether ChatKit should have a separate stricter CORS list from orchestrator API.
- TODO: Confirm final HQ21-side origin set if additional dev domains are introduced.
