# Agent Integration Observability - Spec-First Action Items

Date: 2026-02-09
Status: IN_PROGRESS
Task classification: B (API contract change), E (external integration behavior change)

## 1) Goal and scope
- Add detailed, actionable integration logging for external agents using the public integration endpoints.
- Expose a dedicated API surface for retrieving recent integration logs and filtering by correlation/trace context.
- Expand workflow authoring guidance so agents clearly understand why workflows should be created and how to create them correctly.

Out of scope:
- New persistence entities or DB migrations for integration logs (in-memory operational logs only).
- Changes to workflow execution semantics or node behavior.

## 2) Spec files to update (exact paths)
- `docs/api/openapi.yaml`
- `docs/api/reference.md`
- `docs/architecture/workflow-authoring-agents.md`

No changes planned in this step:
- `docs/api/schemas/*.json` (workflow payload schemas remain unchanged)
- `db/migrations/*.sql` (no DB shape changes)

## 3) Compatibility strategy (additive vs breaking)
- Additive only:
  - New `GET /agent-integration-logs` endpoint.
  - Additional integration-kit URL field for log endpoint discovery.
  - Additional workflow authoring instructions in docs.
- No breaking removals or behavior changes for existing endpoints.

## 4) Implementation files
- `apps/orchestrator/api/app.py`

## 5) Tests (unit/integration/contract/e2e)
- Update API integration tests:
  - `apps/orchestrator/tests/test_api.py`
- Validate architecture/contracts:
  - `./scripts/archctl_validate.sh`
- Validate orchestrator API behavior:
  - `./.venv/bin/python -m pytest apps/orchestrator/tests/test_api.py`

## 6) Observability/security impacts
- Integration logs include request context (correlation/trace/tenant/method/path/status) and validation outcomes.
- Sensitive payload bodies are not logged by default; log details remain metadata-focused.
- Log retrieval endpoint is read-only and supports bounded pagination (`limit` with cap).

## 7) Rollout/rollback notes
- Rollout:
  - Ship spec/docs updates.
  - Deploy API with logging endpoint and updated integration kit links.
  - Verify via integration-test UI and JSON report.
- Rollback:
  - Revert API/docs changes if external integrations depend on previous behavior.
  - No DB rollback required.

## 8) Outstanding TODOs/questions
- TODO: Confirm long-term retention requirement for agent integration logs (in-memory vs persisted store).
- TODO: Confirm whether integration log endpoint should require auth in hardened production profiles.
