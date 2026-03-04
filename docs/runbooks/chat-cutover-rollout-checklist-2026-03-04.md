# Chat Cutover Rollout Checklist (2026-03-04)

Scope:
- Canonical chat path is `POST /chat`.
- Deprecated path is `POST /chatkit`.
- Hosts in scope:
  - `https://api.hq21.tech` (primary)
  - `https://api.runwcr.com` (alias)

Decision locks:
- Hard cutover today.
- No rollback to `/chatkit` path (fix forward only).
- Support both auth profiles:
  - single bearer
  - split bearer

Execution snapshot (UTC `2026-03-04 16:13:02Z`):
- [x] Front Door routing script applied (`deploy_frontdoor.sh`).
- [x] Runtime image deployed on both apps:
  - `acrworkcoreproduaen.azurecr.io/workcore-orchestrator:chat-cutover-20260304-193204`
- [x] Primary domain contract updated:
  - `https://api.hq21.tech/openapi.yaml` exposes `/chat`.
- [x] Secondary domain contract updated:
  - `https://api.runwcr.com/openapi.yaml` exposes `/chat`.
- [x] Secondary custom domain validation:
  - `cd-api-secondary (api.runwcr.com)` is `Approved` and `deploymentStatus=Succeeded`.
- [x] Primary runtime smoke (with production tokens):
  - `/orchestrator/messages` with API token -> `400` (authorized, business-level validation).
  - `/chat` with Chat token -> `500` (authorized, workflow payload invalid in smoke sample).
  - `/chatkit` with API token -> `404`.
- [x] Secondary runtime smoke:
  - `api.runwcr.com` status matrix matches primary host:
    - `/orchestrator/messages` API token -> `400`, Chat token -> `401`
    - `/chat` API token -> `401`, Chat token -> `500` (test workflow payload)
    - `/chatkit` -> `404`

## 1) Pre-cutover communication
- [ ] Send pre-cutover message:
  - `/Users/artemgendler/dev/workcore/docs/integration/chat-cutover-notice-2026-03-04.md`
- [ ] Include integrator curl pack from the same file.
- [ ] Confirm escalation channel and required debug fields:
  - UTC timestamp
  - host + method + path
  - `X-Correlation-Id`
  - response status + body

## 2) Contract preflight
- [ ] Primary host contract check:
```bash
curl -fsS https://api.hq21.tech/openapi.yaml | rg '^  /chat:|^  /chatkit:'
```
- [ ] Alias host contract check:
```bash
curl -fsS https://api.runwcr.com/openapi.yaml | rg '^  /chat:|^  /chatkit:'
```
- [ ] Integration kit check:
```bash
curl -fsS https://api.hq21.tech/agent-integration-kit | rg '\$BASE_URL/chat|\$BASE_URL/chatkit|/chat|/chatkit'
curl -fsS https://api.runwcr.com/agent-integration-kit | rg '\$BASE_URL/chat|\$BASE_URL/chatkit|/chat|/chatkit'
```

## 3) Deploy runtime
- [ ] Build and publish orchestrator image:
```bash
az acr build \
  --registry acrworkcoreproduaen \
  --image workcore-orchestrator:<tag> \
  .
```
- [ ] Deploy apps with new image:
```bash
WORKCORE_IMAGE=acrworkcoreproduaen.azurecr.io/workcore-orchestrator:<tag> \
./deploy/azure/scripts/deploy_apps.sh
```
- [ ] Verify container apps are on new image:
```bash
az containerapp show -g rg-workcore-prod-uaen -n ca-orchestrator --query 'properties.template.containers[0].image' -o tsv
az containerapp show -g rg-workcore-prod-uaen -n ca-chatkit --query 'properties.template.containers[0].image' -o tsv
```

## 4) Deploy edge routing (path split on API host)
- [ ] Apply Front Door routing:
```bash
API_PRIMARY_DOMAIN=api.hq21.tech \
ENABLE_SECONDARY_API_DOMAIN=true \
API_SECONDARY_DOMAIN=api.runwcr.com \
./deploy/azure/scripts/deploy_frontdoor.sh
```
- [ ] Verify primary routes:
```bash
az afd route show -g rg-workcore-prod-uaen --profile-name afd-workcore-prod-uaen --endpoint-name workcore --route-name route-api-primary-chat --query patternsToMatch -o tsv
az afd route show -g rg-workcore-prod-uaen --profile-name afd-workcore-prod-uaen --endpoint-name workcore --route-name route-api-primary --query patternsToMatch -o tsv
```
- [ ] Verify secondary routes:
```bash
az afd route show -g rg-workcore-prod-uaen --profile-name afd-workcore-prod-uaen --endpoint-name workcore --route-name route-api-secondary-chat --query patternsToMatch -o tsv
az afd route show -g rg-workcore-prod-uaen --profile-name afd-workcore-prod-uaen --endpoint-name workcore --route-name route-api-secondary --query patternsToMatch -o tsv
```
- [ ] Verify custom-domain validation status is `Approved` for both API domains:
```bash
az afd custom-domain list \
  --resource-group rg-workcore-prod-uaen \
  --profile-name afd-workcore-prod-uaen \
  --query "[].{name:name,host:hostName,validation:domainValidationState,provisioning:provisioningState}" \
  -o table
```
- [ ] If `cd-api-secondary` is `Pending`, publish/repair DNS validation before cutover complete:
```bash
az afd custom-domain show \
  --resource-group rg-workcore-prod-uaen \
  --profile-name afd-workcore-prod-uaen \
  --custom-domain-name cd-api-secondary \
  --query validationProperties \
  -o json
```
  - Required outcome: `domainValidationState=Approved`.
  - Until approved, `api.runwcr.com` may continue serving legacy origin/config.

## 5) Runtime smoke
- [ ] Primary host (`api.hq21.tech`) with real tenant tokens:
  - `POST /chat` (threads.create) succeeds.
  - `POST /orchestrator/messages` succeeds.
  - `/chatkit` is not used by integrations.
- [ ] Alias host (`api.runwcr.com`) with same checks.
- [ ] Verify auth profiles:
  - single bearer tenant: one token works for both paths.
  - split bearer tenant: orchestrator token on `/orchestrator/*`, chat token on `/chat`.

## 6) Post-cutover communication
- [ ] Send post-cutover message:
  - `/Users/artemgendler/dev/workcore/docs/integration/chat-cutover-notice-2026-03-04.md`
- [ ] Include “cutover complete” timestamp in UTC.
- [ ] Ask teams to report remaining `/chatkit` traffic with correlation IDs.

## 7) Incident mode (fix forward only)
- [ ] If failures detected, keep `/chat` canonical.
- [ ] Apply fix forward at routing/runtime/auth policy layer.
- [ ] Provide manual migration support to affected integrators.
