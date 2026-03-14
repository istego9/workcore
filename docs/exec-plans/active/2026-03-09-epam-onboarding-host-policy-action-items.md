# Partner Host Policy Normalization Action Items

Date: 2026-03-09
Task classification: B + E + F

## 1) Goal and scope
- Normalize partner onboarding host behavior behind explicit policy mapping keyed by `partner_id`.
- Ensure onboarding artifacts for `partner_id=epam_future-insurance` use only `https://api.runwcr.com`.
- Prevent marker-based or "primary/alias host" wording from reappearing in onboarding-facing docs and drift checks.
- Keep request-host behavior unchanged for partners without pinned policy.

In scope:
- Internal self-service onboarding request normalization.
- Generated onboarding ZIP artifacts (`README.md`, `.env.partner`, `integration_manifest.json`, `metadata.json`).
- Internal operator portal defaults and hints.
- Public/partner-facing contract docs and onboarding guidance.
- Drift detection that must reject marker heuristics and primary/alias host framing.

Out of scope:
- Global production host policy for partners without explicit policy mapping.
- APIM runtime routing or public gateway host topology.

## 2) Spec files to update
- `docs/api/openapi.yaml` (review/confirm current `host_policy` contract)
- `docs/api/reference.md` (review/confirm first-class host policy wording)
- `docs/integration/workcore-api-integration-guide.md` (review/confirm policy-driven onboarding wording)
- `docs/integration/partner-self-service-operator-guide.md`
- `docs/architecture/overview.md` (review/confirm onboarding boundary wording)
- `docs/adr/ADR-0013-unified-partner-onboarding-bundle.md` (review/confirm decision record)
- `CHANGELOG.md` (review/confirm additive API diff entry)

## 3) Compatibility strategy
- Additive/non-breaking for public request/manifest shape: `host_policy` remains first-class.
- Behavioral enforcement is explicit and deterministic:
  - `partner_id=epam_future-insurance` resolves to `pinned_runwcr`
  - partners without explicit mapping keep request-host behavior

## 4) Implementation files
- `apps/orchestrator/api/partner_self_service.py`
- `docs/integration/partner-self-service-portal.html`
- `docs/integration/hq21_integration_playbook.md`
- `scripts/check_public_contract_drift.py`
- `apps/orchestrator/tests/test_api.py`

## 5) Tests
- Update internal onboarding API tests for:
  - pinned partner request normalization to `https://api.runwcr.com`
  - pinned `/chat` URL generation
  - allowed domains forced to `api.runwcr.com`
  - doctor FAIL on pinned host mismatch
- Run drift sentinel so docs/code regressions fail fast.
- Run targeted API test module or focused test cases covering partner self-service.

## 6) Observability/security impacts
- No secrets or generated client secrets in logs.
- Pinned host override must happen server-side, not only in browser UI, so manual API calls cannot leak `api.hq21.tech` into issued artifacts for pinned partners.
- Drift checks must guard against reintroducing ambiguous host language in partner onboarding materials.

## 7) Rollout/rollback notes
- Rollout: deploy orchestrator API/docs/sentinel together so bundle generation and contract guidance stay aligned.
- Rollback: revert explicit partner-to-policy mapping changes and accompanying docs/sentinel updates together.

## 8) Outstanding TODOs/questions
- TODO: add future pinned partners only through explicit `partner_id -> host_policy` mapping and update docs/contracts in the same change.
