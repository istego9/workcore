# Azure Deploy Runbook (Codex-First)

Date: 2026-03-04  
Scope: WorkCore runtime on Azure with primary gateway `api.hq21.tech` and optional alias `api.runwcr.com`.

## 1. What this runbook is for

Use this document when you need fast, repeatable deployment and verification from Codex/terminal without rediscovering Azure/GitHub wiring.

This runbook reflects production incident fixes validated on:
- successful deploy workflow run on `main`
- successful insurance classification reruns for `wf_f265975e`

## 2. Operating modes

### Primary-only
- Purpose: safest default rollout.
- Effect: deploy infra/apps/frontdoor with `api.hq21.tech` active and optional alias route disabled.
- Use when: normal production deploys.

### Catalog
- Purpose: preflight inventory/audit of CI, Azure auth, secrets, and runtime config before deploy.
- Effect: read-only checks; no infra changes.
- Use when: onboarding, incident triage, or before critical deploy windows.

### Rollback
- Purpose: return to last known good revision quickly.
- Effect: redeploy previous `main` commit/ref and keep Primary-only unless explicitly needed.
- Use when: post-deploy regressions, runtime instability, or failed external E2E.

### Gateway aliases (not modes)
- Primary gateway: `api.hq21.tech`
- Optional alias: `api.runwcr.com`
- Important: alias points to the same backend path (Cloudflare/Front Door). It is not a separate runtime mode or contour.

## 3. Required baseline (one-time + drift checks)

### GitHub Actions secrets (repo-level)
- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `POSTGRES_ADMIN_PASSWORD`
- `AZURE_OPENAI_API_KEY`
- `WORKCORE_API_AUTH_TOKEN`
- `WEBHOOK_DEFAULT_INBOUND_SECRET`
- `CHATKIT_AUTH_TOKEN`
- `MCP_BRIDGE_AUTH_TOKEN`
- `MINIO_ROOT_USER`
- `MINIO_ROOT_PASSWORD`

### Azure role assignments for GitHub OIDC service principal
- `Contributor` on deployment scope (resource group or subscription)
- `Key Vault Secrets Officer` on `kv-workcore-prod-uaen`

Without `Key Vault Secrets Officer`, foundation step fails on `setSecret` with `ForbiddenByRbac`.

### Azure OpenAI API version (critical)
- Must be `2025-03-01-preview` or newer for Responses API.
- Keep aligned in:
  - Key Vault secret `azure-openai-api-version`
  - container app env vars (`ca-orchestrator`, `ca-chatkit`)
  - deploy defaults in repo

## 4. Primary-only deploy (recommended default)

```bash
./scripts/codex_ci_cd.sh deploy-azure \
  --ref main \
  --resource-group rg-workcore-prod-uaen \
  --location uaenorth \
  --deploy-frontdoor true \
  --enable-secondary-api-domain false
```

Monitor:

```bash
./scripts/codex_ci_cd.sh runs deploy --limit 5
./scripts/codex_ci_cd.sh watch <run-id>
./scripts/codex_ci_cd.sh view <run-id> --log
```

## 5. Gateway alias health check (optional)

Deployment stays Primary-only. If alias routing is already enabled, validate hosts:
- `https://api.hq21.tech/health`
- `https://api.runwcr.com/health`

## 6. Catalog (preflight checklist)

```bash
# GitHub auth and workflows
gh auth status
gh workflow list

# Azure account/subscription context
az account show --output json

# Key Vault secret inventory
az keyvault secret list --vault-name kv-workcore-prod-uaen --query '[].name' -o tsv

# Runtime AOAI API version
az keyvault secret show \
  --vault-name kv-workcore-prod-uaen \
  --name azure-openai-api-version \
  --query value -o tsv

az containerapp show -g rg-workcore-prod-uaen -n ca-orchestrator \
  --query "properties.template.containers[0].env[?name=='AZURE_OPENAI_API_VERSION']" -o json
```

## 7. Insurance verification (classification)

Run immediately after deploy if insurance flow is critical.

Target workflow:
- `project_id=proj_insurance_20260216`
- `workflow_id=wf_f265975e`

Minimal check (recent runs):

```bash
BASE_URL="https://api.hq21.tech"
TOKEN="$(az keyvault secret show --vault-name kv-workcore-prod-uaen --name workcore-api-auth-token --query value -o tsv)"

curl -sS "$BASE_URL/runs?workflow_id=wf_f265975e&limit=10" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-Id: local" \
  -H "X-Project-Id: proj_insurance_20260216" | jq .
```

Expected:
- new runs move to `COMPLETED`
- `node_runs` contains `classify_docs` with `status=RESOLVED`
- ledger tail contains `run_completed`

## 8. Rollback procedure

1. Identify previous stable commit on `main`.
2. Redeploy that ref in Primary-only mode:

```bash
./scripts/codex_ci_cd.sh deploy-azure --ref <stable-sha> --enable-secondary-api-domain false
```

3. Re-run insurance verification (section 7).
4. Keep alias routing unchanged during stabilization unless DNS/Front Door change is explicitly required.

## 9. Known failure signatures and fast fixes

### `HTTP 422 Unexpected inputs provided` on workflow dispatch
- Cause: CLI/script sends inputs not present in workflow definition on target ref.
- Fix: align script + `.github/workflows/deploy-azure.yml` on same branch/ref.

### `Azure login (OIDC)` missing client/tenant/subscription
- Cause: missing `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` / `AZURE_SUBSCRIPTION_ID`.
- Fix: set repo secrets and rerun.

### `POSTGRES_ADMIN_PASSWORD is required`
- Cause: missing GitHub secret.
- Fix: set `POSTGRES_ADMIN_PASSWORD` before deploy.

### `WorkloadProfileCannotRemoveAll`
- Cause: managed environment update attempted with empty workload profile set.
- Fix: ensure Container Apps env keeps explicit `Consumption` profile in Bicep.

### `ForbiddenByRbac` on `Microsoft.KeyVault/vaults/secrets/setSecret/action`
- Cause: OIDC SP lacks Key Vault secret write role.
- Fix: assign `Key Vault Secrets Officer` on `kv-workcore-prod-uaen`.

### `BadRequest ... Responses API is enabled only for api-version 2025-03-01-preview and later`
- Cause: outdated `AZURE_OPENAI_API_VERSION`.
- Fix: set `2025-03-01-preview` in Key Vault + container apps + deploy defaults.
