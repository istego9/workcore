# Artifact References + Run Projection - Spec-First Action Items

Date: 2026-02-18
Status: COMPLETED (spec + implementation + tests completed; live payload/token sampling pending)
Task classification: B (API contract change), C (runtime semantics change), E (integration behavior change), D (DB schema/migration) TBD after design review

## 1) Goal and scope
- Introduce token-efficient document handling by making artifact references the default transport for document page content in run IO paths.
- Prevent large inline payload duplication between `inputs`, `state`, `outputs`, and snapshot events.
- Add explicit run-level projection controls so callers can trim persisted/returned state and outputs.
- Keep extraction quality by allowing explicit content fetch (`read_artifact(ref)` style), while agent defaults remain metadata-first.

Out of scope:
- New workflow node types.
- Redesign of Builder UX patterns.
- Breaking removal of legacy inline document payload mode in the first rollout.

## 2) Spec files to update (exact paths)
- `docs/api/openapi.yaml`
- `docs/api/reference.md`
- `docs/architecture/runtime.md`
- `docs/architecture/executors.md`
- `docs/architecture/streaming.md`
- `docs/architecture/data-model.md`
- `CHANGELOG.md` (required for public API contract updates)

Conditional (only if accepted in design review):
- `docs/api/schemas/workflow-draft.schema.json` (if workflow/node config gains explicit projection or document-mode settings)
- `docs/api/schemas/workflow-export-v1.schema.json` (if Builder export/import must carry new config defaults)
- `docs/adr/ADR-0009-artifact-reference-defaults.md` (if default behavior changes must be captured as architecture decision)
- `db/migrations/010_artifact_projection_support.sql` (only if persistent fields/indexes are required beyond existing JSONB and files/object storage references)

## 3) Compatibility strategy (additive vs breaking)
- Additive phase:
  - Accept both inline and artifact-reference document page payloads.
  - Add optional run request controls: `state_exclude_paths` and `output_include_paths`.
- Default behavior phase:
  - Switch to no-inline-by-default for newly published workflow versions (exact rollout gate/date TBD).
  - Keep legacy inline behavior for previously published versions to avoid runtime regressions.
- Agent behavior:
  - Default agent input must be metadata-only for documents.
  - Full document/page content must be fetched explicitly via artifact-read tool/function.
- Error envelope remains unchanged (`error.code`, `error.message`, optional `details`, `correlation_id`).

## 4) Implementation files
- `apps/orchestrator/api/app.py`
- `apps/orchestrator/api/serializers.py`
- `apps/orchestrator/runtime/engine.py`
- `apps/orchestrator/executors/agent_executor.py`
- `apps/orchestrator/runtime/service.py`
- `apps/orchestrator/runtime/multi_service.py`
- `apps/orchestrator/workflow_engine_adapter/adapter.py`
- `apps/orchestrator/webhooks/service.py`
- `apps/builder/src/App.tsx` (run history document preview compatibility for artifact-only payloads)

Potential persistence touchpoints (if D is approved):
- `apps/orchestrator/api/store.py`
- `db/migrations/*.sql` (new migration file only if storage shape changes are required)

## 5) Tests (unit/integration/contract/e2e)
- API contract tests:
  - `apps/orchestrator/tests/test_api.py`
  - Validate `RunCreateRequest` accepts projections and `Run` responses obey projection controls.
- Executor/runtime tests:
  - `apps/orchestrator/tests/test_agent_executor_event_loop.py`
  - `apps/orchestrator/tests/test_engine.py`
  - Validate metadata-only default agent payload and explicit artifact-read path.
- Serialization/store tests:
  - `apps/orchestrator/tests/test_serializers.py`
  - `apps/orchestrator/tests/test_run_store.py` (if persistence changes are introduced)
- Streaming and integration behavior:
  - Add/extend tests for snapshot payload projection and webhook payload minimization.
- Builder tests (if UI run preview behavior changes):
  - `cd apps/builder && npm run test:unit`

Validation commands (adapt to touched scope):
- `./scripts/archctl_validate.sh`
- `./.venv/bin/python -m pytest apps/orchestrator/tests`
- `cd apps/builder && npm run test:unit`
- `cd apps/builder && npm run test:e2e` (required if run UI/runtime integration path changes)
- `./scripts/dev_check.sh`

## 6) Observability/security impacts
- Add metrics for payload-size and token-efficiency outcomes:
  - `run_payload_bytes_before_projection`
  - `run_payload_bytes_after_projection`
  - `snapshot_payload_bytes_after_projection`
  - `artifact_read_count`
  - `artifact_read_error_count`
  - `token_reduction_estimate`
- Keep sensitive content out of logs:
  - Never log inline binary/document body by default.
  - Log only artifact metadata (`artifact_ref`, mime, size, page count) with tenant/correlation context.
- Enforce tenant/project-scoped authorization for artifact reads.
- Preserve correlation and trace propagation across run start, agent tool calls, SSE, and webhooks.

## 7) Rollout/rollback notes
- Rollout:
  - Step 1: ship additive contract + implementation behind feature flag/default-off.
  - Step 2: enable for selected projects/workflows and capture payload/token deltas.
  - Step 3: make no-inline-by-default active for newly published workflow versions.
- Rollback:
  - Disable feature flag and restore legacy inline behavior for new runs.
  - Keep additive fields in API contract (safe no-op when feature disabled).
  - If DB migration is added, ensure backward-compatible rollback plan (no destructive migration in first release).

## 8) Outstanding TODOs/questions
- TODO: Attach before/after payload size and token usage samples from live production runs for rollout report.

## Proposed contract delta (for OpenAPI draft)
- `RunCreateRequest`:
  - add optional `state_exclude_paths: string[]`
  - add optional `output_include_paths: string[]`
- Document payload semantics:
  - `documents[].pages[]` should support `artifact_ref` as preferred content carrier.
  - Inline `image_base64` remains compatibility path during migration window.
- Agent default context:
  - document metadata only by default (`doc_id`, `filename`, `mime_type`, `page_count`, optional preview metadata)
  - full content retrieved only via explicit artifact-read call.
