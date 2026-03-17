# Execution Plan: External Audit Remediation

## Metadata
- Date: 2026-03-17
- Owner: Codex
- Task classification: B / E / F
- Related issue/spec: external audit remediation for release pipeline, run debug, and service handoff

## Goal and scope
- Goal: close the external audit gaps around live operator proof, authoritative bind readback, export content validation, runbooks, and `App.tsx` surface decomposition.
- In scope:
  - public API additive readback for project workflow definitions
  - builder bind-state readback and export hardening
  - live operator Playwright acceptance + CI lane
  - release pipeline runbook and service handoff artifact
  - extraction of non-canvas modal surfaces from `App.tsx`
- Out of scope:
  - DB schema changes
  - new public doc versioning system
  - external service rollout board maintained inside this repo

## Mandatory action items (required for A-E)
1. Goal and scope
2. Spec files to update (exact paths)
3. Compatibility strategy (additive vs breaking)
4. Implementation files
5. Tests (unit/integration/contract/e2e)
6. Observability/security impacts
7. Rollout/rollback notes
8. Outstanding TODOs/questions

## Implementation plan (iterations)
1. Iteration 1: spec-first docs and contract updates.
2. Iteration 2: orchestrator read/list endpoints and builder bind readback.
3. Iteration 3: live operator acceptance lane and export JSON assertions.
4. Iteration 4: runbook/handoff docs and `App.tsx` modal extraction.

## Validation plan
- Commands to run:
  - `./scripts/archctl_validate.sh`
  - `python -m pytest apps/orchestrator/tests`
  - `cd apps/builder && npm run test:unit`
  - `cd apps/builder && npm run test:e2e`
  - `cd apps/builder && npm run test:e2e:operator-live`
- Expected outcomes:
  - workflow-definition readback is available and non-breaking
  - bind stage uses server confirmation
  - release report/support bundle content is asserted
  - operator live artifacts are retained in CI
- Evidence artifacts:
  - release report JSON
  - support bundle JSON
  - acceptance screenshots
  - runbook and handoff docs

## Rollout and rollback
- Rollout steps:
  - ship additive GET endpoints and builder readback first
  - add operator live lane as separate CI signal
  - make the new lane required after stabilization
- Rollback trigger:
  - live lane proves flaky or readback endpoints regress existing routing flows
- Rollback steps:
  - keep POST upsert path unchanged
  - disable the new required lane before removing code changes
  - revert builder readback UI only if needed while preserving backend read endpoints

## Decision log
- 2026-03-17: use additive GET endpoints instead of DB/schema changes because store/data model already support workflow-definition read/list.
- 2026-03-17: keep external service work as handoff artifact instead of in-repo conformance board.

## Post-completion notes
- What changed from the original plan:
  - pending implementation review
- Follow-up tasks:
  - consider renaming `fullstack-chat-contract` after branch protection is updated
