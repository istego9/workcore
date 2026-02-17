# Project Orchestrators + Intent Routing + Workflow Switching (MVP) Action Items

Status: In progress
Owner: Platform backend
Date: 2026-02-13

## 1) Goal and scope
- [x] Implement project-scoped orchestration entrypoint for user messages.
- [x] Support routing modes: orchestrated and direct workflow.
- [x] Add intent routing with disambiguation/fallback and workflow switching policy.
- [x] Persist orchestration decisions and session workflow stack.
- [x] Integrate OpenAI Responses API for strict structured routing decisions.

## 2) Spec files to update (exact paths)
- [x] `docs/api/openapi.yaml`
- [x] `docs/api/schemas/routing-decision.schema.json`
- [x] `db/migrations/005_project_orchestrators.sql`
- [x] `docs/architecture/data-model.md`
- [x] `docs/architecture/runtime.md`
- [x] `docs/architecture/overview.md`

## 3) Compatibility strategy (additive vs breaking)
- [x] Additive API changes only (new endpoints, new schemas).
- [x] Existing workflow/run endpoints remain backward compatible.
- [x] New DB tables/columns are additive and idempotent.
- [x] Existing run execution semantics are preserved; orchestration is an additional entrypoint.

## 4) Implementation files
- [x] `apps/orchestrator/project_router/*`
- [x] `apps/orchestrator/workflow_engine_adapter/*`
- [x] `apps/orchestrator/orchestrator_runtime/*`
- [x] `apps/orchestrator/llm_adapter/*`
- [x] `apps/orchestrator/api/app.py`

## 5) Tests (unit/integration/contract/e2e)
- [x] Unit tests for router validation and policy decisions.
- [x] Unit/contract tests for strict routing schema output handling.
- [x] Integration tests for endpoint routing modes and cancel behavior.
- [ ] E2E coverage expansion for chat routing path (post-MVP follow-up).

## 6) Observability/security impacts
- [x] Structured decision logs persisted per inbound message.
- [x] Execution adapter logs include correlation identifiers.
- [x] Error model follows existing envelope (`error.code`, `error.message`, `correlation_id`).
- [ ] PII redaction policy for orchestrator prompts/context (TODO for hardening pass).

## 7) Rollout/rollback notes
- [x] Feature flag gate: `ORCHESTRATOR_ENABLED` (default disabled).
- [x] Project-level flag in project settings: `orchestrator_enabled`.
- [x] Rollback path: disable flag and continue using direct workflow APIs.

## 8) Outstanding TODOs/questions
- [ ] Confirm production thresholds per project (`confidence_threshold`, `switch_margin`).
- [ ] Confirm default fallback workflow behavior for projects without fallback configured.
- [ ] Decide final policy for non-cancellable states (`operator` transfer vs explicit refusal) per project.
