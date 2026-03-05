# Partner Self-Service Onboarding Action Items (2026-03-05)

## Classification
- A: new internal gateway-facing admin subsystem (`/internal/partner-access`)
- B: API contract change (`docs/api/openapi.yaml`)
- E: external integration behavior change (automated Entra app onboarding + APIM mapping from UI)

## 1) Goal and scope
- Provide an internal-only self-service for operators to onboard partner apps with minimal inputs.
- Generate a downloadable ZIP package containing partner-specific onboarding artifacts (`README.md`, `.env.partner`).
- Reuse existing onboarding automation (`deploy/azure/scripts/apim_partner_onboard.sh`) instead of duplicating Entra/APIM logic.

## 2) Spec files to update
- `docs/api/openapi.yaml`
- `docs/api/reference.md`
- `CHANGELOG.md`

## 3) Compatibility strategy
- Additive.
- No changes to existing partner-facing payloads or URL contracts.
- New endpoints are internal operator endpoints and disabled unless explicitly enabled by env configuration.

## 4) Implementation files
- `apps/orchestrator/api/app.py`
- `apps/orchestrator/api/partner_self_service.py` (new)
- `docs/integration/partner-self-service-portal.html` (new)

## 5) Tests
- Update `apps/orchestrator/tests/test_api.py` with:
  - Entra gate checks for internal portal endpoints.
  - ZIP package generation smoke (mocked onboarding script runner).
  - Disabled-portal behavior checks.

## 6) Observability/security impacts
- Require Entra EasyAuth principal header (`X-MS-CLIENT-PRINCIPAL`).
- Optional tenant/user allowlist enforcement for internal portal access.
- Never log generated client secret values.
- Return standard error envelope with correlation id on failures.

## 7) Rollout/rollback notes
- Rollout: enable with `WORKCORE_PARTNER_PORTAL_ENABLED=1` and tenant guard env in pre-prod, validate, then prod.
- Rollback: set `WORKCORE_PARTNER_PORTAL_ENABLED=0` (endpoints return 404/disabled).

## 8) Outstanding TODOs/questions
- Deployment must ensure host environment has Azure CLI available for script execution.
- Confirm final hosting path for EasyAuth-protected access in production routing.
