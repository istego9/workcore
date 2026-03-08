# Partner OAuth Resource Fix Action Items

## Classification
- E: external integration behavior change

## 1) Goal and scope
- Restore working partner OAuth onboarding without changing the published audience contract.
- Ensure onboarding automation grants the required Entra application role to each partner service principal.
- Document the required Entra resource application state for APIM partner auth.

## 2) Spec files to update
- None. Public audience string remains `api://workcore-partner-api/.default`.

## 3) Compatibility strategy
- Non-breaking fix.
- Preserve current public `scope` value and APIM audience validation contract.
- Add guardrails so onboarding fails fast if the resource API app is missing or misconfigured.

## 4) Implementation files
- `deploy/azure/scripts/apim_partner_onboard.sh`
- `docs/deploy/azure-workcore-deployment.md`

## 5) Tests
- `bash -n deploy/azure/scripts/apim_partner_onboard.sh`
- Live validation:
  - token exchange with generated partner credentials
  - protected API call through `https://api.runwcr.com`

## 6) Observability/security impacts
- Do not log client secrets.
- Fail with explicit onboarding error if the OAuth resource audience cannot be resolved.
- Keep app-role assignment idempotent.

## 7) Rollout/rollback notes
- Rollout: repair Entra resource app audience alias, assign app role, rerun token/API smoke.
- Rollback: remove the added alias URI or app-role assignment only if auth model must be reverted intentionally.

## 8) Outstanding TODOs/questions
- TODO: decide whether the Entra resource app should be provisioned automatically by infra scripts instead of as a platform prerequisite.
