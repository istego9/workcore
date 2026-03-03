#!/usr/bin/env bash
set -euo pipefail

AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-rg-workcore-prod-uaen}"
AFD_PROFILE_NAME="${AFD_PROFILE_NAME:-afd-workcore-prod-uaen}"
AFD_ENDPOINT_NAME="${AFD_ENDPOINT_NAME:-workcore}"
KEY_VAULT_NAME="${KEY_VAULT_NAME:-kv-workcore-prod-uaen}"

API_PRIMARY_DOMAIN="${API_PRIMARY_DOMAIN:-api.hq21.tech}"
API_SECONDARY_DOMAIN="${API_SECONDARY_DOMAIN:-api.runwcr.com}"

echo "[preflight] Azure account"
az account show --query "{name:name, subscription:id, tenant:tenantId}" -o table

echo "[preflight] Resource group"
az group show --name "${AZ_RESOURCE_GROUP}" --query "{name:name, location:location}" -o table >/dev/null
az group show --name "${AZ_RESOURCE_GROUP}" --query "{name:name, location:location}" -o table

echo "[preflight] Key Vault"
az keyvault show --name "${KEY_VAULT_NAME}" --resource-group "${AZ_RESOURCE_GROUP}" --query "{name:name, vaultUri:properties.vaultUri}" -o table

echo "[preflight] Required Key Vault secrets"
required_secrets=(
  workcore-database-url
  chatkit-database-url
  workcore-api-auth-token
  webhook-default-inbound-secret
  chatkit-auth-token
  minio-root-user
  minio-root-password
  mcp-bridge-auth-token
  azure-openai-endpoint
  azure-openai-api-key
  azure-openai-api-version
)

missing=0
for secret_name in "${required_secrets[@]}"; do
  if az keyvault secret show --vault-name "${KEY_VAULT_NAME}" --name "${secret_name}" --query id -o tsv >/dev/null 2>&1; then
    echo "  [ok] ${secret_name}"
  else
    echo "  [missing] ${secret_name}"
    missing=$((missing + 1))
  fi
done

echo "[preflight] Front Door endpoint"
if az afd endpoint show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --endpoint-name "${AFD_ENDPOINT_NAME}" >/dev/null 2>&1; then
  endpoint_host="$(az afd endpoint show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --endpoint-name "${AFD_ENDPOINT_NAME}" --query hostName -o tsv)"
  echo "  endpoint host: ${endpoint_host}"
else
  echo "  endpoint not created yet (will be created by deploy_frontdoor.sh)"
  endpoint_host=""
fi

echo "[preflight] DNS guidance"
echo "  primary API domain : ${API_PRIMARY_DOMAIN}"
echo "  secondary API domain: ${API_SECONDARY_DOMAIN}"
if [[ -n "${endpoint_host}" ]]; then
  echo "  Create CNAME records:"
  echo "    ${API_PRIMARY_DOMAIN} -> ${endpoint_host}"
  echo "    ${API_SECONDARY_DOMAIN} -> ${endpoint_host}"
fi

if [[ "${missing}" -gt 0 ]]; then
  echo "[preflight] FAILED: ${missing} required secrets are missing" >&2
  exit 1
fi

echo "[preflight] OK"
