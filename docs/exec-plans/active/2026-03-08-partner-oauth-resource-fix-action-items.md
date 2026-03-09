# Partner OAuth Resource Fix Action Items

## Classification
- E: external integration behavior change

## 1) Goal and scope
- Restore working partner OAuth onboarding without changing the published audience contract.
- Ensure onboarding automation grants the required Entra application role to each partner service principal.
- Document the required Entra resource application state for APIM partner auth.
- Ensure APIM JWT validation accepts the actual Entra `aud` form emitted for `api://workcore-partner-api/.default`.

## 2) Spec files to update
- None. Public audience string remains `api://workcore-partner-api/.default`.

## 3) Compatibility strategy
- Non-breaking fix.
- Preserve current public `scope` value and APIM audience validation contract.
- Add guardrails so onboarding fails fast if the resource API app is missing or misconfigured.
- Accept both the public audience alias and the resolved Entra resource app ID in APIM policy.

## 4) Implementation files
- `deploy/azure/scripts/apim_partner_onboard.sh`
- `deploy/azure/scripts/deploy_apim.sh`
- `apps/orchestrator/api/partner_self_service.py`
- `docs/deploy/azure-workcore-deployment.md`
- `docs/api/reference.md`
- `docs/integration/workcore-api-integration-guide.md`
- `docs/integration/apim-partner-onboarding-guide.md`
- `apps/orchestrator/tests/test_api.py`

## 5) Tests
- `bash -n deploy/azure/scripts/apim_partner_onboard.sh`
- `bash -n deploy/azure/scripts/deploy_apim.sh`
- Live validation:
  - token exchange with generated partner credentials
  - protected API call through `https://api.hq21.tech`
  - protected API call through `https://api.runwcr.com`
  - partner onboarding ZIP contains decoded-JWT audience note

## 6) Observability/security impacts
- Do not log client secrets.
- Fail with explicit onboarding error if the OAuth resource audience cannot be resolved.
- Keep app-role assignment idempotent.

## 7) Rollout/rollback notes
- Rollout: repair Entra resource app audience alias, assign app role, rerun token/API smoke.
- Rollback: remove the added alias URI or app-role assignment only if auth model must be reverted intentionally.

## 8) Outstanding TODOs/questions
- TODO: decide whether the Entra resource app should be provisioned automatically by infra scripts instead of as a platform prerequisite.
