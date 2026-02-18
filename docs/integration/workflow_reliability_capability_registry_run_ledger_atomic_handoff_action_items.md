# Workflow Reliability - Spec-First Action Items

Date: 2026-02-18
Status: COMPLETED
Task classification: A (new reliability modules), B (API contract), C (runtime/event semantics), D (DB migration), E (integration behavior)

## 1) Goal and scope
- Add a versioned Capability Registry so workflow steps can pin capability version and avoid implicit regressions.
- Add immutable Run Ledger records for end-to-end execution traceability (`workflow/version`, `run`, `step`, chosen capability/version, status, decisions, artifacts, timestamp).
- Add Atomic Handoff API for single-request workflow package intake (context, constraints, expected result, acceptance checks) with idempotency and deterministic replay support.

Out of scope:
- Redesign of workflow builder UX.
- New workflow node types.
- Breaking change to existing run/start/resume/cancel APIs.

## 2) Spec files to update (exact paths)
- `docs/api/openapi.yaml`
- `docs/api/schemas/workflow-draft.schema.json`
- `docs/api/reference.md`
- `docs/architecture/data-model.md`
- `docs/architecture/runtime.md`
- `docs/architecture/streaming.md`
- `CHANGELOG.md` (required for API contract update)

## 3) Compatibility strategy (additive vs breaking)
- Additive only:
  - New endpoints for capabilities, handoff, and run ledger.
  - Optional capability pin fields in node config (`capability_id`, `capability_version`).
  - Existing workflow/run APIs remain supported without mandatory payload changes.
- Existing workflows without capability pins continue to run unchanged.
- Deterministic replay is opt-in via handoff request.

## 4) Implementation files
- `apps/orchestrator/api/app.py`
- `apps/orchestrator/api/serializers.py`
- `apps/orchestrator/runtime/multi_service.py`
- `apps/orchestrator/api/capability_store.py` (new)
- `apps/orchestrator/api/ledger_store.py` (new)
- `apps/orchestrator/api/handoff_store.py` (new)
- `db/migrations/010_capabilities_ledger_handoffs.sql` (new)

## 5) Tests (unit/integration/contract/e2e)
- API tests:
  - `apps/orchestrator/tests/test_api.py`:
    - capability registry create/list
    - run start with capability pin validation
    - run ledger retrieval
    - handoff create and deterministic replay
- Relevant checks:
  - `./scripts/archctl_validate.sh`
  - `./.venv/bin/python -m pytest apps/orchestrator/tests/test_api.py`

## 6) Observability/security impacts
- Run ledger is append-only; no update/delete path exposed.
- No secrets in ledger payload by default; store only provided workflow package fields and runtime event payload.
- Continue propagating `correlation_id`/`trace_id` and tenant scope to reliability artifacts.
- Idempotency rules remain tenant-scoped.

## 7) Rollout/rollback notes
- Rollout:
  - Apply migration.
  - Deploy API/runtime with additive endpoints.
  - Validate with new API tests and smoke checks.
- Rollback:
  - API/runtime rollback is safe; new tables are additive and can remain.
  - Existing endpoints/flows continue operating without new features.

## 8) Outstanding TODOs/questions
- TODO: Confirm long-term retention/TTL policy for `run_ledger` and `workflow_handoffs`.
- TODO: Confirm whether deterministic replay should lock external tool outputs or only freeze input package/version pin.
- TODO: Confirm if capability contracts should enforce strict JSON Schema validation for step input/output at runtime (follow-up hardening).
