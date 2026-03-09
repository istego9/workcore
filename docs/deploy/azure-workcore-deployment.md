# Azure Deployment Plan: WorkCore (UAE North, Production-Lite)

Date: 2026-03-03  
Status: Approved for implementation

## Task classification
- `E`: external integration/deployment behavior
- `C`: event/streaming durability semantics
- `D`: persisted runtime behavior (existing schema usage, no breaking migration)

## Action items checklist (Spec-First mandatory)
1. Goal and scope  
Deploy WorkCore to Azure (`UAE North`) with hardening and single replica per service; use Azure OpenAI for agent/router/STT; close in-memory durability gaps for SSE and webhooks.
2. Spec files updated  
- `docs/architecture/streaming.md`
- `docs/architecture/webhooks.md`
- `docs/architecture/executors.md`
- `docs/runbooks/orchestrator-runtime.md`
- `docs/runbooks/streaming-sse.md`
- `docs/runbooks/webhooks-delivery.md`
- `docs/deploy/azure-workcore-deployment.md`
3. Compatibility strategy  
Additive/non-breaking: public API contracts unchanged, OpenAPI unchanged, behavior switches via env backends.
4. Implementation files  
- `deploy/azure/*` (Bicep + scripts)
- `apps/orchestrator/streaming/*`
- `apps/orchestrator/runtime/service.py`
- `apps/orchestrator/runtime/multi_service.py`
- `apps/orchestrator/webhooks/store.py`
- `apps/orchestrator/webhooks/service.py`
- `apps/orchestrator/chatkit/service.py`
- `.github/workflows/deploy-azure.yml`
5. Tests  
Unit + integration for backend selection, SSE replay after restart, webhook recovery/idempotency, Azure STT provider wiring.
6. Observability/security impacts  
Front Door WAF, Key Vault, managed identity/OIDC in CI, centralized logs/alerts, explicit CORS and auth headers.
7. Rollout/rollback notes  
Blue/green via Container Apps revisions + Front Door origin switch; rollback by revision swap and optional temporary backend fallback.
8. Outstanding TODOs/questions  
No open product decisions for this iteration; Blob-native replacement for MinIO is out of scope.

## Target architecture
- Edge ingress: Azure Front Door Standard + WAF
- API gateway: Azure API Management Standard v2 (`apim-workcore-prod-uaen`)
- UI: Azure Static Web Apps (regional exception: hosted in `West Europe`, because SWA is unavailable in `UAE North`)
- Runtime:
  - `orchestrator` in Azure Container Apps (`min=1`, `max=1`)
  - `chatkit` in Azure Container Apps (`min=1`, `max=1`)
  - `mcp-bridge` internal-only Container App (`min=1`, `max=1`)
  - `minio` internal-only Container App with Azure Files volume (`min=1`, `max=1`)
- Networking:
  - dedicated PostgreSQL delegated subnet (`snet-postgres-flex`)
  - dedicated Container Apps delegated subnet (`snet-containerapps`, `Microsoft.App/environments`)
- Data:
  - Azure Database for PostgreSQL Flexible Server (`B2s`, private access)
  - Key Vault for secrets (RBAC)
  - Azure Container Registry (Basic)
- Observability:
  - Log Analytics workspace
  - Azure Monitor alerts + action group
- Model layer:
  - Azure OpenAI in `UAE North` only

## Domain strategy (dual API domain)
- Primary API domain: `api.hq21.tech`
- Secondary API domain: `api.runwcr.com`
- Rollout policy:
  - Primary is enabled in Front Door from first deployment.
  - Secondary is created but enabled only after smoke validation (controlled by deploy input `enable_secondary_api_domain`).
- Front Door routing:
  - `route-api-primary` -> APIM origin group
  - `route-api-secondary` -> APIM origin group (optional cutover route)
- DNS:
  - both API hostnames must CNAME to Front Door endpoint hostname.

## UI domain strategy
- UI custom domain: `wrk.hq21.tech`
- Front Door route:
  - `route-workcore-custom` -> `og-ui` (SWA origin), `link-to-default-domain=Disabled`
- DNS records required for activation:
  - `CNAME wrk.hq21.tech -> <frontdoor-endpoint>.z02.azurefd.net`
  - `TXT _dnsauth.wrk.hq21.tech -> <validation token from cd-workcore>`
- Until DNS validation completes, the Front Door default host remains the temporary UI URL.

## UI access control (Microsoft Entra ID)
- Access model:
  - SWA route policy requires `allowedRoles: ["authenticated"]`.
  - Unauthenticated requests are redirected to `/.auth/login/aad`.
- Identity provider:
  - Azure Static Web Apps built-in auth provider `aad` (Microsoft Entra ID).
  - Required SWA app settings:
    - `AZURE_CLIENT_ID`
    - `AZURE_CLIENT_SECRET`
    - `AZURE_TENANT_ID`
- Operational guidance:
  - Keep provider secrets in Key Vault; inject via deployment pipeline.
  - Use single-tenant Entra app registration for organization-only access.

## Runtime data flow
1. User opens `workcore.<domain>` through Front Door.
2. Front Door routes UI to Static Web Apps.
3. Front Door routes API calls on `api.<domain>` to APIM gateway.
4. APIM validates Entra OAuth2 access token, resolves partner mapping (`appid` -> pinned tenant), and forwards to upstream runtime:
   - `/chat*` -> `chatkit`
   - all other protected API paths -> `orchestrator`
5. Microsoft Entra resource app for APIM partner auth must exist with:
   - identifier URI `api://workcore-partner-api`
   - APIM policy must accept both the public alias and the resolved Entra resource app ID as valid JWT audiences
   - application role `workcore.api.access`
   - a service principal in the same tenant so onboarding can create app-role assignments for partner clients
6. Runtime writes run state to PostgreSQL.
7. SSE `/runs/{run_id}/stream` replays from Postgres-backed event store and survives container restart.
8. Webhook subscriptions/deliveries/idempotency persist in PostgreSQL and dispatcher resumes after restart.
9. Agent/router/STT calls use Azure OpenAI deployments in `UAE North`.

## Azure OpenAI profile (`UAE North`)
- Account: Azure OpenAI resource in `uaenorth`.
- Deployments:
  - `wf-agent` -> `OpenAI.gpt-5-chat.*` (fallback `OpenAI.gpt-4.1.*`)
  - `wf-router` -> `OpenAI.gpt-5-mini.*` (fallback `OpenAI.gpt-4.1-mini.*`)
  - `wf-stt` -> `OpenAI.whisper.001`
- Runtime env:
  - `AZURE_OPENAI_ENDPOINT`
  - `AZURE_OPENAI_API_KEY`
  - `AZURE_OPENAI_API_VERSION`
  - `OPENAI_API=responses`
  - `OPENAI_MODEL=wf-agent`
  - `ORCHESTRATOR_MODEL_ID=wf-router`
  - `CHATKIT_STT_MODEL=wf-stt`
  - `CHATKIT_STT_API_KEY=<azure key>`

## Backend selectors (durability)
- `STREAMING_STORE_BACKEND=memory|postgres`  
  Azure profile requires `postgres`.
- `WEBHOOK_STORE_BACKEND=memory|postgres`  
  Azure profile requires `postgres`.
- Existing public endpoints remain unchanged.

## Security baseline
- WAF policy with managed rules on Front Door.
- Entra OAuth2 client_credentials at APIM edge for external partners.
- APIM tenant pinning: external `X-Tenant-Id` is overridden by gateway partner mapping.
- Internal partner self-service endpoints require Entra EasyAuth principal header and optional tenant/user allowlist:
  - `WORKCORE_PARTNER_PORTAL_ENABLED=1`
  - `WORKCORE_PARTNER_PORTAL_ALLOWED_TENANT_ID=<internal_tenant>`
  - `WORKCORE_PARTNER_PORTAL_ALLOWED_USER_EMAILS=<comma-separated-upns>` (recommended)
- Private PostgreSQL access via delegated subnet.
- Secrets in Key Vault, no plaintext secrets in CI or manifests.
- GitHub Actions OIDC to Azure (no long-lived cloud credentials).
- Auth/CORS/env hardening stays enabled (`WORKCORE_ALLOW_INSECURE_DEV=0`).
- UI endpoints are protected by Entra login gate in SWA (`authenticated` role).

## Rollout
1. Deploy infra foundation.
2. Build/push images to ACR.
3. Deploy runtime revisions.
4. Run migrations job.
5. Deploy APIM API import + policy (`deploy_apim.sh`) and partner mapping named value.
6. Run APIM pre-prod smoke with partner OAuth clients.
7. Deploy Front Door with `api.hq21.tech` as primary API route to APIM.
8. Run smoke/e2e checks against primary API domain.
9. Enable secondary API route (`api.runwcr.com`) and run secondary-domain smoke.
10. Keep both routes active or use secondary as staged cutover endpoint.

## Existing environment migration note
- If Container Apps environment was created before VNet integration, recreate it after deleting dependent apps/jobs so private PostgreSQL DNS resolves from runtime containers.

## Rollback
1. Keep APIM deployed, but switch Front Door API routes back to runtime origins (`orchestrator` + `chatkit`) for emergency bypass.
2. Revert to previous Container Apps revision if runtime regression is detected.
3. If emergency mitigation is needed, temporarily set:
   - `STREAMING_STORE_BACKEND=memory`
   - `WEBHOOK_STORE_BACKEND=memory`
4. Restore durable mode after fix and verification.

## Acceptance checks
- `./scripts/archctl_validate.sh`
- `./.venv/bin/python -m pytest apps/orchestrator/tests`
- `cd apps/builder && npm run test:unit`
- `cd apps/builder && npm run test:e2e` (smoke against Azure URL)
- `./scripts/dev_check.sh` (local regression baseline)

## Automation and operator commands
- Preflight dual-domain readiness:
  - `./deploy/azure/scripts/preflight_dual_api_domains.sh`
- Deploy APIM gateway configuration:
  - `./deploy/azure/scripts/deploy_apim.sh`
- Partner onboarding and secret lifecycle:
  - `./deploy/azure/scripts/apim_partner_onboard.sh`
    - resolves the OAuth resource app from `APIM_OAUTH_AUDIENCE`
    - ensures partner service principal has the required application app-role assignment
  - `./deploy/azure/scripts/apim_partner_rotate_secret.sh`
  - `./deploy/azure/scripts/apim_partner_revoke.sh`
- Internal self-service onboarding portal:
  - `GET /internal/partner-access`
  - `POST /internal/partner-access/onboard-package`
  - operator runbook: `docs/integration/partner-self-service-operator-guide.md`
- Deploy builder UI artifact to Static Web Apps:
  - `./deploy/azure/scripts/deploy_builder_swa.sh`
- Configure SWA Entra auth app settings:
  - `./deploy/azure/scripts/configure_swa_entra_auth.sh`
- Full deploy via GitHub workflow:
  - `.github/workflows/deploy-azure.yml`
- Direct Front Door apply:
  - `./deploy/azure/scripts/deploy_frontdoor.sh`
    - `API_PRIMARY_DOMAIN=api.hq21.tech`
    - `API_SECONDARY_DOMAIN=api.runwcr.com`
    - `ENABLE_SECONDARY_API_DOMAIN=false|true`
