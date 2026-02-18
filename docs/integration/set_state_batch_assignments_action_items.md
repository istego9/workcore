# Set State Batch Assignments - Spec-First Action Items

Date: 2026-02-18
Status: COMPLETED
Task classification: A (authoring/runtime capability), B (API/schema contract), C (runtime semantics), E (agent integration behavior)

## 1) Goal and scope
- Reduce oversized workflows by allowing one `set_state` node to apply multiple state writes in one execution step.
- Keep backward compatibility for existing drafts using legacy `set_state` fields (`target` + `expression`).
- Expose updated contract and guidance through Agent Integration Kit resources (`/workflow-authoring-guide`, `/schemas/workflow-draft.schema.json`, `/agent-integration-kit*`).

Out of scope:
- New workflow node types.
- DB schema/migration changes.
- Changes to run/event storage shape.

## 2) Spec files to update (exact paths)
- `docs/api/openapi.yaml`
- `docs/api/schemas/workflow-draft.schema.json`
- `docs/api/reference.md`
- `docs/architecture/node-semantics.md`
- `docs/architecture/state-and-expressions.md`
- `docs/architecture/workflow-authoring-agents.md`
- `docs/adr/ADR-0008-set-state-batch-assignments.md`
- `CHANGELOG.md` (required for API contract updates)

## 3) Compatibility strategy (additive vs breaking)
- Additive:
  - `set_state.config.assignments[]` becomes supported.
  - Legacy `set_state.config.target` + `set_state.config.expression` remains supported.
- Runtime applies `assignments[]` when present; legacy fields are fallback.
- No endpoint removals or request envelope changes.

## 4) Implementation files
- `apps/orchestrator/runtime/engine.py`
- `apps/orchestrator/api/app.py`
- `apps/builder/src/builder/graph.ts`
- `apps/builder/src/App.tsx`

## 5) Tests (unit/integration/contract/e2e)
- Runtime unit tests:
  - `apps/orchestrator/tests/test_engine.py`
- API/integration-kit tests:
  - `apps/orchestrator/tests/test_api.py`
- Builder unit tests:
  - `apps/builder/src/builder/graph.test.ts`

Relevant validation commands:
- `./scripts/archctl_validate.sh`
- `./.venv/bin/python -m pytest apps/orchestrator/tests/test_engine.py apps/orchestrator/tests/test_api.py`
- `cd apps/builder && npm run test:unit`

## 6) Observability/security impacts
- No new sensitive payload logging.
- Agent Integration Kit checks should verify schema contains batch assignment contract for external agent onboarding.
- Existing correlation/trace propagation remains unchanged.

## 7) Rollout/rollback notes
- Rollout:
  - Ship spec/docs updates first.
  - Deploy runtime + builder support in same release window.
  - Validate via integration kit report and builder/unit tests.
- Rollback:
  - Revert runtime/builder changes; legacy `target` + `expression` path remains intact.
  - No DB rollback required.

## 8) Outstanding TODOs/questions
- TODO: Decide whether to add explicit max assignment count per `set_state` node (not enforced in this change).
- TODO: Confirm if future expression language migration requires additional assignment metadata.
