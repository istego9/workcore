# Agent Integration Doc Refresh Action Items

Date: 2026-03-09
Task classification: E (external integration behavior change), F (docs sync)

## 1) Goal and scope
- Restore public agent integration entrypoints so they publish externally usable URLs.
- Align agent integration docs with the current `/chat` public contract and deprecated `/chatkit` status.
- Fix integration test/log UX so public pages do not imply anonymous access to protected log data.

## 2) Spec files to update
- `docs/api/reference.md`
- `docs/integration/workcore-api-integration-guide.md`

## 3) Compatibility strategy
- Additive/non-breaking for API surface: no endpoint removals or payload changes.
- Corrective for public documentation and generated links: keep existing routes, fix emitted host values and stale doc text.

## 4) Implementation files
- `apps/orchestrator/api/app.py`
- `apps/orchestrator/tests/test_api.py`
- `docs/integration/workcore-api-integration-guide.html`

## 5) Tests
- Update/add targeted API tests for public doc URL host resolution.
- Update/add targeted API tests for integration test UI log-auth messaging.
- Re-run relevant `apps/orchestrator/tests/test_api.py` cases.

## 6) Observability/security impacts
- Preserve bearer auth on `/agent-integration-logs`.
- Ensure public docs do not leak internal ACA hostnames in generated URLs.
- Keep integration log guidance explicit that bearer auth is required.

## 7) Rollout/rollback notes
- Deploy orchestrator API and re-import APIM/OpenAPI so public hosts stop advertising stale `/chatkit` contract.
- Verify both `https://api.hq21.tech` and `https://api.runwcr.com` after rollout.
- Rollback is safe by redeploying previous app version, but would reintroduce internal-host links and stale docs.

## 8) Outstanding TODOs/questions
- TODO: confirm APIM import/release step in deployment pipeline so live OpenAPI matches repo after rollout.
