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
  - `route-api-primary` -> orchestrator origin group
  - `route-api-secondary` -> orchestrator origin group (optional cutover route)
- DNS:
  - both API hostnames must CNAME to Front Door endpoint hostname.

## Runtime data flow
1. User opens `workcore.<domain>` through Front Door.
2. Front Door routes UI to Static Web Apps.
3. Front Door routes API calls to `api.<domain>` (`orchestrator`) and `chatkit.<domain>` (`chatkit`).
4. Runtime writes run state to PostgreSQL.
5. SSE `/runs/{run_id}/stream` replays from Postgres-backed event store and survives container restart.
6. Webhook subscriptions/deliveries/idempotency persist in PostgreSQL and dispatcher resumes after restart.
7. Agent/router/STT calls use Azure OpenAI deployments in `UAE North`.

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
- Private PostgreSQL access via delegated subnet.
- Secrets in Key Vault, no plaintext secrets in CI or manifests.
- GitHub Actions OIDC to Azure (no long-lived cloud credentials).
- Auth/CORS/env hardening stays enabled (`WORKCORE_ALLOW_INSECURE_DEV=0`).

## Rollout
1. Deploy infra foundation.
2. Build/push images to ACR.
3. Deploy runtime revisions.
4. Run migrations job.
5. Deploy Front Door with `api.hq21.tech` as primary API route.
6. Run smoke/e2e checks against primary API domain.
7. Enable secondary API route (`api.runwcr.com`) and run secondary-domain smoke.
8. Keep both routes active or use secondary as staged cutover endpoint.

## Existing environment migration note
- If Container Apps environment was created before VNet integration, recreate it after deleting dependent apps/jobs so private PostgreSQL DNS resolves from runtime containers.

## Rollback
1. Revert to previous Container Apps revision.
2. Switch Front Door origin to previous stable backend.
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
- Full deploy via GitHub workflow:
  - `.github/workflows/deploy-azure.yml`
- Direct Front Door apply:
  - `./deploy/azure/scripts/deploy_frontdoor.sh`
    - `API_PRIMARY_DOMAIN=api.hq21.tech`
    - `API_SECONDARY_DOMAIN=api.runwcr.com`
    - `ENABLE_SECONDARY_API_DOMAIN=false|true`
