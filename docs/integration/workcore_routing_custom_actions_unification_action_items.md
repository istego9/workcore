# WorkCore Routing + Custom Actions Unification - Spec-First Action Items

Date: 2026-02-20
Status: IN PROGRESS (P0 delivered, P1.1/P1.2 delivered, P1.3+ pending)
Task classification: A (new subsystem pieces), B (API/schema contract), C (runtime/event semantics), D (DB migration), E (external integration behavior)

## Execution update (2026-02-20)
- P0 implemented:
  - `threads.custom_action` canonical `action_type` + alias handling in WorkCore ChatKit server.
  - Orchestrator context API (`/orchestrator/context/get|set|unset`) with tenant+project scoped persistence.
  - Non-MCP `integration_http` node runtime support with auth/timeout/retry and response-to-state mapping.
  - Profile-like prefill pattern via session context hydration into workflow inputs.
- Spec-first artifacts updated before implementation:
  - OpenAPI, JSON schema, runtime/chatkit/architecture docs, changelog, DB migration.
- Validation completed:
  - `./scripts/archctl_validate.sh`
  - `./.venv/bin/python -m pytest apps/orchestrator/tests`
  - `./scripts/dev_check.sh`
- P1.1 implemented:
  - Native submit payload normalization in ChatKit custom actions:
    - flatten wrapper maps (`input`/`form`/`form_data`/`fields`)
    - scalar typing for safe primitive literals
    - `documents` passthrough
    - projection path validation for `state_exclude_paths` / `output_include_paths`
- P1.2 implemented:
  - `POST /orchestrator/messages` now returns `decision_trace` with:
    - candidates + scores
    - selected action/workflow
    - selection reason and switch reason details

## Current-state gap assessment (against request)
- P0.1 `threads.custom_action`: partially implemented in ChatKit runtime, but only for a fixed action enum and without a canonical `action_type` contract + explicit alias map.
- P0.2 thread/session context API: not implemented; only orchestrator session routing state exists (`active_run_id`, disambiguation fields), no generic `context.set/get/unset` API.
- P0.3 integration HTTP node (non-MCP): not implemented in runtime engine/executors.
- P0.4 profile-like flow pattern (`context + integration + prefill`): no standard first-class workflow pattern yet; behavior is still distributed.
- P1.1 custom action payload normalization: implemented natively in ChatKit runtime + documented in OpenAPI/reference.
- P1.2 decision trace in response: implemented as standardized `decision_trace` object in orchestrator message response.
- P1.3 standardized route/action error contract: partial (`error.code/error.message/correlation_id` exists), but route/action-specific catalog is not standardized end-to-end.
- P2.1 routing policy knobs: current policy supports `confidence_threshold`, `switch_margin`, `max_disambiguation_turns`, `top_k_candidates`; no `sticky`, `allow_switch`, `explicit_switch_only`, `cooldown`.
- P2.2 anti-flip/hysteresis: partially approximated via `switch_margin`; no explicit hysteresis/cooldown policy model.
- P2.3 replay/eval mode for routing quality: not available for orchestrator routing decisions (handoff deterministic replay exists, but not routing replay/eval).

## 1) Goal and scope
- [ ] Unify routing/custom-action orchestration inside WorkCore so backend-specific routing/prefill logic can be removed.
- [ ] Deliver P0/P1/P2 in sequenced phases with additive compatibility first.
- [ ] Keep existing workflow/run APIs and tenant scoping behavior backward compatible unless explicitly approved as breaking.

Out of scope (for this track):
- [ ] Re-design of builder UX outside required node/config exposure.
- [ ] Replacing ChatKit protocol itself.
- [ ] Introducing new frameworks/dependencies without explicit approval.

## 2) Spec files to update (exact paths)
P0 (required before implementation):
- [ ] `docs/api/openapi.yaml`
- [ ] `docs/api/reference.md`
- [ ] `docs/architecture/runtime.md`
- [ ] `docs/architecture/chatkit.md`
- [ ] `docs/architecture/node-semantics.md`
- [ ] `docs/architecture/data-model.md`
- [ ] `docs/api/schemas/workflow-draft.schema.json` (if HTTP node config is added to workflow schema)
- [ ] `db/migrations/011_routing_context_and_actions.sql` (new, name tentative)
- [ ] `CHANGELOG.md` (required for public API deltas)

P1 (required before implementation):
- [ ] `docs/api/openapi.yaml`
- [ ] `docs/api/schemas/routing-decision.schema.json` (if decision trace contract is extended)
- [ ] `docs/architecture/runtime.md`
- [ ] `docs/architecture/streaming.md` (if trace payload is streamed)
- [ ] `CHANGELOG.md`

P2 (required before implementation):
- [ ] `docs/api/openapi.yaml`
- [ ] `docs/architecture/runtime.md`
- [ ] `docs/architecture/overview.md`
- [ ] `docs/adr/ADR-0010-routing-policy-and-eval.md` (new, tentative)
- [ ] `db/migrations/012_routing_policy_hysteresis_eval.sql` (new, tentative)
- [ ] `CHANGELOG.md`

## 3) Compatibility strategy (additive vs breaking)
- [ ] Default strategy: additive.
- [ ] Keep existing custom action payload paths working while introducing canonical `action_type` and alias mapping.
- [ ] Preserve current orchestrator behavior via defaults when new routing policy fields are absent.
- [ ] Introduce new context API without removing existing session-state behavior.
- [ ] Any planned deprecations must include explicit timeline and fallback behavior in docs/changelog.

## 4) Implementation files
P0 target files (expected):
- [ ] `apps/orchestrator/api/app.py`
- [ ] `apps/orchestrator/chatkit/server.py`
- [ ] `apps/orchestrator/chatkit/service.py`
- [ ] `apps/orchestrator/project_router/router.py`
- [ ] `apps/orchestrator/orchestrator_runtime/runtime.py`
- [ ] `apps/orchestrator/orchestrator_runtime/store.py`
- [ ] `apps/orchestrator/runtime/engine.py`
- [ ] `apps/orchestrator/runtime/multi_service.py`
- [ ] `apps/orchestrator/executors/*` (new HTTP/integration executor module, if approved)
- [ ] `apps/orchestrator/tests/*` (targeted updates + new tests)

P1/P2 additional expected files:
- [ ] `apps/orchestrator/llm_adapter/responses_router.py`
- [ ] `apps/orchestrator/orchestrator_runtime/runtime.py`
- [ ] `apps/orchestrator/orchestrator_runtime/store.py`
- [ ] `apps/orchestrator/tests/test_project_router.py`
- [ ] `apps/orchestrator/tests/test_api.py`

## 5) Tests (unit/integration/contract/e2e)
- [ ] Contract tests for new/updated OpenAPI endpoints and schemas.
- [ ] Unit tests for action canonicalization/alias mapping and payload normalization.
- [ ] Integration tests for thread context persistence (`set/get/unset`) and routing with active sessions.
- [ ] Runtime tests for HTTP integration node timeout/retry/auth behavior.
- [ ] Regression tests for current `threads.create`, `threads.add_user_message`, `threads.custom_action` flows.
- [ ] Decision-trace tests validating candidates/scores/chosen-workflow/reason exposure.
- [ ] Routing policy tests for sticky/switch/cooldown/hysteresis behavior.
- [ ] Replay/eval tests for offline routing reproducibility.

Validation commands:
- [ ] `./scripts/archctl_validate.sh`
- [ ] `./.venv/bin/python -m pytest apps/orchestrator/tests`
- [ ] `cd apps/builder && npm run test:unit` (if builder node authoring/validation is touched)
- [ ] `cd apps/builder && npm run test:e2e` (if UI/runtime integration path is touched)
- [ ] `./scripts/dev_check.sh`

## 6) Observability/security impacts
- [ ] Add structured logs/metrics for action normalization decisions, alias resolution, and routing policy outcomes.
- [ ] Add decision-trace observability with correlation and tenant IDs.
- [ ] Ensure no sensitive payloads (auth headers, PII, full documents) are logged by default.
- [ ] Define allowlist/guardrails for HTTP integration node destinations, headers, and secrets usage.
- [ ] Preserve idempotency guarantees for custom actions and routing entrypoints.

## 7) Rollout/rollback notes
- [ ] Phase rollout by priority: P0 -> P1 -> P2.
- [ ] Use feature flags for new routing behaviors and HTTP node execution.
- [ ] Rollback path for each phase must be non-destructive (disable flags, keep additive schema fields).
- [ ] DB migrations must be additive/idempotent and safe to keep if runtime is rolled back.

## 8) Outstanding TODOs/questions
- [ ] Confirm canonical `action_type` enum and full alias map (source payload variants and expected canonical values).
- [ ] Confirm exact context API contract and scope semantics:
  - thread vs session keyspace
  - conflict rules
  - TTL/versioning requirements
- [ ] Confirm HTTP integration node contract:
  - allowed auth modes
  - retry/backoff policy
  - timeout defaults and maximums
  - state mapping DSL and validation rules
- [ ] Confirm decision-trace response schema fields and whether trace should be persisted, returned, streamed, or all three.
- [ ] Confirm standardized route/action error code catalog (codes, retryability semantics, HTTP status mapping).
- [ ] Confirm P2 routing-policy precedence and interaction matrix for `sticky`, `allow_switch`, `explicit_switch_only`, `cooldown`.
- [ ] Confirm replay/eval scope: offline only vs production shadow mode, and required quality metrics.

## Rough phase estimate (implementation + tests + docs)
- P0: 2.0-3.0 weeks (largest unknown is HTTP node + context contract finalization)
- P1: 1.0-1.5 weeks
- P2: 1.5-2.5 weeks
- Total: 4.5-7.0 weeks (single squad), assuming no blocking contract changes after kickoff.
