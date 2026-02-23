# WorkCore Runtime Security + Routing Harness Action Items

Date: 2026-02-20
Status: DONE
Task classification: C (runtime semantics), E (external integration behavior), B (API response contract alignment)

## 1) Goal and scope
- [x] Harden `integration_http` outbound behavior with runtime egress policy guardrails.
- [x] Fix ChatKit custom-action idempotency flow for validation early-return paths.
- [x] Align context API validation status behavior to a single contract (`422`).
- [x] Add repeatable routing quality harness gate for autonomous/CI regression detection.

Out of scope:
- [x] Full orchestrator module split (`api/app.py`, `runtime.py`) in this change.
- [x] New infrastructure/services.

## 2) Spec files to update (exact paths)
- [x] `docs/api/openapi.yaml`
- [x] `docs/api/reference.md`
- [x] `docs/architecture/runtime.md`
- [x] `docs/architecture/executors.md`
- [x] `docs/architecture/chatkit.md`
- [x] `CHANGELOG.md`

## 3) Compatibility strategy (additive vs breaking)
- [x] Runtime hardening changes are behavior-tightening (security) without new public payload fields.
- [x] Context API validation status normalization to `422` is treated as a contract clarification/update.
- [x] Preserve request/response body shapes for existing endpoints.

## 4) Implementation files
- [x] `apps/orchestrator/executors/integration_http_executor.py`
- [x] `apps/orchestrator/api/app.py`
- [x] `apps/orchestrator/chatkit/server.py`
- [x] `apps/orchestrator/chatkit/service.py`
- [x] `apps/orchestrator/chatkit/app.py`
- [x] `apps/orchestrator/tests/test_integration_http_executor.py`
- [x] `apps/orchestrator/tests/test_chatkit.py`
- [x] `apps/orchestrator/tests/test_api.py`
- [x] `apps/orchestrator/tests/test_routing_harness.py`
- [x] `apps/orchestrator/tests/fixtures/routing_eval/baseline.json`

## 5) Tests (unit/integration/contract/e2e)
- [x] Unit tests for integration HTTP egress policy allow/deny behavior.
- [x] ChatKit regression test for idempotency retry after submit validation failure.
- [x] API tests for context endpoint validation status (`422`).
- [x] Routing harness test using deterministic replay fixture + threshold assertions.

Validation commands:
- [x] `./.venv/bin/python -m pytest apps/orchestrator/tests/test_integration_http_executor.py`
- [x] `./.venv/bin/python -m pytest apps/orchestrator/tests/test_chatkit.py -k submit_action`
- [x] `./.venv/bin/python -m pytest apps/orchestrator/tests/test_api.py -k orchestrator_context`
- [x] `./.venv/bin/python -m pytest apps/orchestrator/tests/test_routing_harness.py`
- [x] `./scripts/archctl_validate.sh`

## 6) Observability/security impacts
- [x] Security: deny-by-default outbound host policy for `integration_http` executor.
- [x] Security: private/link-local/loopback host blocking unless explicitly enabled.
- [x] Reliability: no idempotency-key lock on pre-execution submit validation errors.
- [x] Quality: replay/eval harness converted into deterministic regression test.

## 7) Rollout/rollback notes
- [x] Rollout: set `INTEGRATION_HTTP_ALLOWED_HOSTS` for environments using `integration_http` nodes.
- [x] Rollback: revert to previous executor behavior if immediate integration breakage occurs.
- [x] Rollback for context status alignment is low-risk (error code class only).

## 8) Outstanding TODOs/questions
- [x] TODO: Decide if per-tenant/project egress policy (DB-backed) is required beyond env-level policy.
- [x] TODO: Decide if routing harness thresholds should be branch-specific or globally fixed.
- [x] TODO: Decide whether to enforce `validate_runtime_security_env()` at app startup by default.
