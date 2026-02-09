# External Client Chat Integration - Spec-First Action Items

Date: 2026-02-07
Status: IN_PROGRESS
Task classification: B (API contract change), C (event/stream semantics change), E (external integration behavior change)

## 1) Goal and scope
- Ensure third-party client integrations include chat as a first-class contract surface, not a side channel.
- Define the supported `/chatkit` request/response contract for thread start, user message continuation, and interrupt actions.
- Define how chat interactions map to run/interrupt lifecycle and delivery fallbacks.

Out of scope:
- New transport protocols beyond existing ChatKit + SSE + webhooks.
- New persistence entities or schema changes in this step.

## 2) Spec files to update (exact paths)
- `docs/api/openapi.yaml`
- `docs/architecture/chatkit.md`
- `docs/api/reference.md`
- `docs/integration/hq21_integration_playbook.md`

No changes planned in this step:
- `docs/api/schemas/*.json` (workflow authoring schemas unchanged)
- `db/migrations/*.sql` (no DB shape changes)
- `docs/architecture/data-model.md` (no new persisted entities)

## 3) Compatibility strategy (additive vs breaking)
- Additive only:
  - Add explicit ChatKit request/response schemas and examples.
  - Add external-client metadata mapping guidance.
  - Clarify idempotency and fallback delivery patterns.
- No breaking field removals or behavior changes.

## 4) Implementation files
- `apps/orchestrator/chatkit/service.py` (reference behavior only; no code changes in this step)
- `apps/orchestrator/chatkit/server.py` (reference behavior only; no code changes in this step)
- `apps/orchestrator/webhooks/service.py` (reference behavior only; no code changes in this step)

## 5) Tests (unit/integration/contract/e2e)
- Contract/docs checks:
  - `./scripts/archctl_validate.sh`
- Runtime regression confidence (recommended next implementation step if behavior changes are introduced):
  - `./.venv/bin/python -m pytest apps/orchestrator/tests/test_chatkit.py`
  - `./.venv/bin/python -m pytest apps/orchestrator/tests/test_api.py`
  - `./.venv/bin/python -m pytest apps/orchestrator/tests/test_webhooks.py`

## 6) Observability/security impacts
- Keep `correlation_id` and tenant scoping explicit in integration guidance.
- Keep `Idempotency-Key` guidance explicit for chat actions and webhook fallbacks.
- Confirm chat endpoint auth requirement when `CHATKIT_AUTH_TOKEN` is enabled.
- No new sensitive payload logging is introduced by this spec update.

## 7) Rollout/rollback notes
- Rollout:
  - Ship docs/spec updates first.
  - Update external client adapters to follow explicit `/chatkit` contract.
  - Validate against staging with chat + interrupt flow smoke checks.
- Rollback:
  - Revert documentation version if integration guidance causes ambiguity.
  - Since this step is additive docs/contracts only, runtime rollback is not required.

## 8) Outstanding TODOs/questions
- TODO: Decide if external user/session identifiers must be standardized as strict fields or remain integration metadata conventions.
- TODO: Decide if outbound webhook payload should include chat thread identifier for easier external reconciliation.
- TODO: Confirm whether `interrupt.cancel` should remain unsupported or be promoted to supported action in a later contract version.
