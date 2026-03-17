# WorkCore UI Domain + Entra ID Gate Action Items (2026-03-03)

## Task classification
- `E`: external integration/deployment behavior change (UI edge domain, SWA deployment, identity provider auth)
- `F`: docs and runbook update

## 1) Goal and scope
Deploy the workflow builder UI to Azure Static Web Apps, expose it via `wrk.hq21.tech` through Front Door, and protect UI access behind Microsoft Entra ID login.

## 2) Spec files to update
- `docs/deploy/azure-workcore-deployment.md`
- This action-item file: `docs/integration/swa_entra_ui_domain_action_items_2026-03-03.md`

## 3) Compatibility strategy
- Additive and non-breaking for public API contracts.
- Existing API behavior (`api.hq21.tech`) remains unchanged.
- UI access policy becomes stricter (`authenticated` role required) for SWA-hosted routes.

## 4) Implementation files
- `apps/builder/public/staticwebapp.config.json` (SWA route auth policy and login redirect)
- `deploy/azure/scripts/deploy_builder_swa.sh` (build and publish builder assets to SWA)
- `deploy/azure/scripts/deploy_frontdoor.sh` (stable custom-domain route attach flow)
- `.github/workflows/deploy-azure.yml` (builder deploy + optional Entra ID app settings wiring)

## 5) Tests
- Build validation: `cd apps/builder && npm run build`
- Auth config presence validation: verify `dist/staticwebapp.config.json` exists in build artifact.
- Runtime smoke:
  - unauthenticated `GET https://wrk.hq21.tech/` redirects to `/.auth/login/aad`
  - `https://wrk.hq21.tech/.auth/login/aad` returns provider redirect (not provider-missing error)
- Front Door domain activation smoke:
  - `wrk.hq21.tech` certificate subject/SAN resolves to custom domain after validation.

## 6) Observability/security impacts
- UI origin remains SWA; edge is Front Door.
- Access control moved to SWA role policy with Entra ID provider.
- Secrets (`AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`) must be stored in Key Vault and injected to SWA app settings via deploy path.
- No bearer API token leakage into frontend bundle.

## 7) Rollout/rollback notes
- Rollout:
  - publish builder to SWA
  - attach `wrk.hq21.tech` in Front Door
  - complete DNS CNAME/TXT validation
  - enable Entra settings and verify login
- Rollback:
  - remove auth-gating config from SWA artifact and redeploy
  - fallback UI endpoint remains Front Door default domain
  - keep API domain unaffected

## 8) Outstanding TODOs/questions
- Confirm Entra app registration owner and secret rotation interval.
- Confirm whether access should be tenant-wide (`authenticated`) or invite-only custom role policy.
