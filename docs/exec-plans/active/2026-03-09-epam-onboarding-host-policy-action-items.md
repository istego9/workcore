# EPAM Onboarding Host Policy Action Items

Date: 2026-03-09
Task classification: E (external integration behavior change), B (documented internal API behavior change)

## 1) Goal and scope
- Ensure partner onboarding artifacts for EPAM partners use only `https://api.runwcr.com`.
- Prevent `https://api.hq21.tech` from appearing in generated onboarding ZIP contents or self-service defaults for EPAM partner requests.
- Keep non-EPAM onboarding behavior unchanged.

In scope:
- Internal self-service onboarding request normalization.
- Generated onboarding ZIP artifacts (`README.md`, `.env.partner`, `metadata.json`).
- Internal operator portal defaults and hints.
- Contract/docs that describe internal onboarding default host behavior.

Out of scope:
- Global production host policy for non-EPAM partners.
- APIM runtime routing or public gateway host topology.

## 2) Spec files to update
- `docs/api/openapi.yaml`
- `docs/api/reference.md`
- `docs/integration/partner-self-service-operator-guide.md`
- `CHANGELOG.md`

## 3) Compatibility strategy
- Additive/non-breaking for request schema shape.
- Behavioral change for internal onboarding defaults:
  - if partner identity contains `epam`, onboarding output is pinned to `https://api.runwcr.com`
  - non-EPAM partners keep the existing default host behavior

## 4) Implementation files
- `apps/orchestrator/api/partner_self_service.py`
- `docs/integration/partner-self-service-portal.html`
- `apps/orchestrator/tests/test_api.py`

## 5) Tests
- Update internal onboarding API tests for:
  - EPAM request normalization to `https://api.runwcr.com`
  - EPAM allowed domains forced to `api.runwcr.com`
  - non-EPAM requests preserving existing defaults
- Run targeted API test module or focused test cases covering partner self-service.

## 6) Observability/security impacts
- No secrets or generated client secrets in logs.
- EPAM host override must happen server-side, not only in browser UI, so manual API calls cannot leak `api.hq21.tech` into issued artifacts.

## 7) Rollout/rollback notes
- Rollout: deploy orchestrator API with updated onboarding normalization and portal assets.
- Rollback: revert the EPAM-specific normalization logic to restore existing default host behavior.

## 8) Outstanding TODOs/questions
- TODO: decide whether EPAM detection should remain substring-based (`epam`) or move to an explicit partner policy field if more partner-specific rules appear.
