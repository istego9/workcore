# HQ21 <-> WorkCore v1 Action Items

Status legend:
- `DONE`: implemented and validated
- `IN_PROGRESS`: partially implemented
- `TODO`: not implemented yet

## Integration readiness checklist
1. `DONE` Fix OpenAPI v1 contract and version it
2. `TODO` Add `workcore_run_id` to HQ21 data model (no FK breakage)
3. `TODO` Implement HQ21 backend integration adapter in HQ21 repo
4. `IN_PROGRESS` Implement `document_import_v1` workflow in WorkCore
5. `IN_PROGRESS` Add quality gate + schema validation nodes
6. `IN_PROGRESS` Add interrupt UX for top-level review
7. `TODO` Add run status endpoint/screen in HQ21
8. `IN_PROGRESS` Publish Python SDK
9. `TODO` Publish npm client/types
10. `IN_PROGRESS` Configure service auth + secrets + key rotation
11. `IN_PROGRESS` Configure observability + alerts
12. `IN_PROGRESS` Add contract/integration/E2E tests
13. `DONE` Prepare docs: integration guide, runbook, incident SOP
14. `TODO` Gate rollout under feature flag
15. `TODO` Stage rollout dev -> staging -> prod

## What is already completed in WorkCore
- Tenant-scoped workflow/run APIs.
- Tenant-scoped idempotency for mutating APIs.
- Correlation/trace propagation through run metadata and events.
- SSE sequence and reconnect support (`Last-Event-ID`).
- Optional bearer auth gate (`WORKCORE_API_AUTH_TOKEN`).
- OpenAPI and API conventions updated.
- Orchestrator + ChatKit E2E smoke scenarios passing.
- HQ21 integration playbook added: `docs/integration/hq21_integration_playbook.md`.
- Unified local E2E runner (`./scripts/e2e_suite.sh`) covering backend + ChatKit + builder Playwright.

## Next implementation slice
1. Finalize `document_import_v1` runtime graph with strict output schemas per phase.
2. Add runbook and incident SOP under `docs/`.
3. Add npm SDK generation/publication pipeline from OpenAPI.
4. `DONE` Add HQ21-facing integration playbook (field mapping, retries, rollback).
