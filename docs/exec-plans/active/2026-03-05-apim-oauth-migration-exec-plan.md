# APIM + Entra OAuth Migration (Big-Bang)

Date: 2026-03-05  
Task classification: `A`, `B`, `E`

## 1) Goal and scope
- Move external partner authentication to APIM + Microsoft Entra OAuth2 client_credentials.
- Keep existing public API domains (`api.hq21.tech`, `api.runwcr.com`) and payload contracts unchanged.
- Keep internal runtime bearer secrets (`WORKCORE_API_AUTH_TOKEN`, `CHATKIT_AUTH_TOKEN`) internal-only.

Out of scope:
- Business logic changes inside orchestrator/chatkit runtime.
- GraphQL or non-existing API surfaces.

## 2) Spec files to update (exact paths)
- `docs/api/openapi.yaml`
- `docs/api/reference.md`
- `docs/integration/workcore-api-integration-guide.md`
- `docs/deploy/azure-workcore-deployment.md`
- `CHANGELOG.md`

## 3) Compatibility strategy
- Additive migration on public API:
  - endpoints, payloads, and response schemas remain unchanged.
  - auth acquisition model changes from shared bearer distribution to OAuth access token issuance.
- Runtime internal compatibility preserved:
  - APIM forwards existing internal bearer tokens to upstream services.

## 4) Implementation files
- `deploy/azure/foundation.bicep`
- `deploy/azure/parameters.prod.example.json`
- `deploy/azure/scripts/deploy_infra.sh`
- `deploy/azure/scripts/deploy_apim.sh`
- `deploy/azure/scripts/deploy_frontdoor.sh`
- `deploy/azure/scripts/preflight_dual_api_domains.sh`
- `.github/workflows/deploy-azure.yml`
- `scripts/codex_ci_cd.sh`
- `deploy/azure/config/partners.yaml`
- `deploy/azure/scripts/apim_partner_onboard.sh`
- `deploy/azure/scripts/apim_partner_rotate_secret.sh`
- `deploy/azure/scripts/apim_partner_revoke.sh`

## 5) Tests and validation
- Script syntax validation:
  - `bash -n deploy/azure/scripts/deploy_apim.sh`
  - `bash -n deploy/azure/scripts/apim_partner_onboard.sh`
  - `bash -n deploy/azure/scripts/apim_partner_rotate_secret.sh`
  - `bash -n deploy/azure/scripts/apim_partner_revoke.sh`
  - `bash -n deploy/azure/scripts/deploy_frontdoor.sh`
  - `bash -n scripts/codex_ci_cd.sh`
- Required repo checks before merge:
  - `./scripts/archctl_validate.sh`
  - `./.venv/bin/python -m pytest apps/orchestrator/tests`
  - `./scripts/dev_check.sh`

## 6) Observability/security impacts
- APIM enforces OAuth JWT validation for protected routes.
- APIM applies partner mapping (`appid` -> pinned `X-Tenant-Id`) and rejects unknown app IDs when enforcement is enabled.
- APIM injects internal upstream bearer tokens and removes need to disclose runtime secrets externally.
- Front Door routes API domains to APIM gateway for centralized auth control.

## 7) Rollout/rollback notes
- Rollout:
  - deploy infra (with APIM resource),
  - deploy runtime apps,
  - deploy APIM policy and partner map,
  - switch Front Door API routes to APIM.
- Rollback:
  - switch Front Door API routes back to direct runtime origins,
  - keep APIM deployed for postmortem/recovery iteration.

## 8) Outstanding TODOs/questions
- Validate APIM root API path behavior (`APIM_API_PATH=""`) in target subscription; if needed, set explicit path + Front Door rewrite.
- Confirm Microsoft Graph app permissions in deployment principal for automated partner onboarding scripts.
- Add pre-prod partner onboarding dry-run evidence and production cutover checklist execution log.
