#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
FOUNDATION_OUTPUTS_PATH="${FOUNDATION_OUTPUTS_PATH:-/tmp/workcore-foundation-outputs.json}"

AZ_LOCATION="${AZ_LOCATION:-uaenorth}"
AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-rg-workcore-prod-uaen}"

ACR_NAME="${ACR_NAME:-acrworkcoreproduaen}"
KEY_VAULT_NAME="${KEY_VAULT_NAME:-kv-workcore-prod-uaen}"
LOG_ANALYTICS_NAME="${LOG_ANALYTICS_NAME:-law-workcore-prod-uaen}"
ACA_ENV_NAME="${ACA_ENV_NAME:-cae-workcore-prod-uaen}"
STORAGE_ACCOUNT_NAME="${STORAGE_ACCOUNT_NAME:-stworkcoreproduaen}"
MINIO_SHARE_NAME="${MINIO_SHARE_NAME:-minio-data}"
SWA_NAME="${SWA_NAME:-swa-workcore-prod-uaen}"
SWA_LOCATION="${SWA_LOCATION:-westeurope}"
AOAI_ACCOUNT_NAME="${AOAI_ACCOUNT_NAME:-aoai-workcore-prod-uaen}"
VNET_NAME="${VNET_NAME:-vnet-workcore-prod-uaen}"
POSTGRES_SUBNET_NAME="${POSTGRES_SUBNET_NAME:-snet-postgres-flex}"
CONTAINERAPPS_SUBNET_NAME="${CONTAINERAPPS_SUBNET_NAME:-snet-containerapps}"
CONTAINERAPPS_SUBNET_PREFIX="${CONTAINERAPPS_SUBNET_PREFIX:-10.42.2.0/23}"
POSTGRES_SERVER_NAME="${POSTGRES_SERVER_NAME:-pg-workcore-prod-uaen}"
POSTGRES_DB_NAME="${POSTGRES_DB_NAME:-workflow}"
POSTGRES_ADMIN_LOGIN="${POSTGRES_ADMIN_LOGIN:-workcoreadmin}"
POSTGRES_SKU_NAME="${POSTGRES_SKU_NAME:-Standard_B2s}"
POSTGRES_SKU_TIER="${POSTGRES_SKU_TIER:-Burstable}"
POSTGRES_BACKUP_RETENTION_DAYS="${POSTGRES_BACKUP_RETENTION_DAYS:-14}"

if [[ -z "${POSTGRES_ADMIN_PASSWORD:-}" ]]; then
  echo "POSTGRES_ADMIN_PASSWORD is required" >&2
  exit 1
fi

echo "[infra] ensuring resource group ${AZ_RESOURCE_GROUP} (${AZ_LOCATION})"
az group create \
  --name "${AZ_RESOURCE_GROUP}" \
  --location "${AZ_LOCATION}" \
  --output none

echo "[infra] deploying foundation.bicep"
az deployment group create \
  --resource-group "${AZ_RESOURCE_GROUP}" \
  --template-file "${ROOT_DIR}/deploy/azure/foundation.bicep" \
  --parameters \
    location="${AZ_LOCATION}" \
    acrName="${ACR_NAME}" \
    keyVaultName="${KEY_VAULT_NAME}" \
    logAnalyticsName="${LOG_ANALYTICS_NAME}" \
    containerAppsEnvName="${ACA_ENV_NAME}" \
    storageAccountName="${STORAGE_ACCOUNT_NAME}" \
    minioShareName="${MINIO_SHARE_NAME}" \
    staticWebAppName="${SWA_NAME}" \
    staticWebAppLocation="${SWA_LOCATION}" \
    azureOpenAIAccountName="${AOAI_ACCOUNT_NAME}" \
    vnetName="${VNET_NAME}" \
    postgresSubnetName="${POSTGRES_SUBNET_NAME}" \
    containerAppsSubnetName="${CONTAINERAPPS_SUBNET_NAME}" \
    containerAppsSubnetPrefix="${CONTAINERAPPS_SUBNET_PREFIX}" \
    postgresServerName="${POSTGRES_SERVER_NAME}" \
    postgresAdminLogin="${POSTGRES_ADMIN_LOGIN}" \
    postgresAdminPassword="${POSTGRES_ADMIN_PASSWORD}" \
    postgresDatabaseName="${POSTGRES_DB_NAME}" \
    postgresSkuName="${POSTGRES_SKU_NAME}" \
    postgresSkuTier="${POSTGRES_SKU_TIER}" \
    postgresBackupRetentionDays="${POSTGRES_BACKUP_RETENTION_DAYS}" \
  --query properties.outputs > "${FOUNDATION_OUTPUTS_PATH}"

POSTGRES_FQDN="$(az postgres flexible-server show \
  --resource-group "${AZ_RESOURCE_GROUP}" \
  --name "${POSTGRES_SERVER_NAME}" \
  --query fullyQualifiedDomainName \
  --output tsv)"

urlencode() {
  local raw="$1"
  local out=""
  local i ch
  for ((i = 0; i < ${#raw}; i++)); do
    ch="${raw:i:1}"
    case "${ch}" in
      [a-zA-Z0-9.~_-])
        out+="${ch}"
        ;;
      *)
        printf -v ch '%%%02X' "'${ch}"
        out+="${ch}"
        ;;
    esac
  done
  echo "${out}"
}

DB_USER_ENCODED="$(urlencode "${POSTGRES_ADMIN_LOGIN}")"
DB_PASSWORD_ENCODED="$(urlencode "${POSTGRES_ADMIN_PASSWORD}")"
DB_URL="postgresql://${DB_USER_ENCODED}:${DB_PASSWORD_ENCODED}@${POSTGRES_FQDN}:5432/${POSTGRES_DB_NAME}?sslmode=require"

echo "[infra] writing runtime secrets into Key Vault (${KEY_VAULT_NAME})"
az keyvault secret set --vault-name "${KEY_VAULT_NAME}" --name "workcore-database-url" --value "${DB_URL}" --output none
az keyvault secret set --vault-name "${KEY_VAULT_NAME}" --name "chatkit-database-url" --value "${DB_URL}" --output none

# Optional secret bootstrap: set these env vars before running script to seed Key Vault.
[[ -n "${WORKCORE_API_AUTH_TOKEN:-}" ]] && az keyvault secret set --vault-name "${KEY_VAULT_NAME}" --name "workcore-api-auth-token" --value "${WORKCORE_API_AUTH_TOKEN}" --output none
[[ -n "${WEBHOOK_DEFAULT_INBOUND_SECRET:-}" ]] && az keyvault secret set --vault-name "${KEY_VAULT_NAME}" --name "webhook-default-inbound-secret" --value "${WEBHOOK_DEFAULT_INBOUND_SECRET}" --output none
[[ -n "${CHATKIT_AUTH_TOKEN:-}" ]] && az keyvault secret set --vault-name "${KEY_VAULT_NAME}" --name "chatkit-auth-token" --value "${CHATKIT_AUTH_TOKEN}" --output none
[[ -n "${MINIO_ROOT_USER:-}" ]] && az keyvault secret set --vault-name "${KEY_VAULT_NAME}" --name "minio-root-user" --value "${MINIO_ROOT_USER}" --output none
[[ -n "${MINIO_ROOT_PASSWORD:-}" ]] && az keyvault secret set --vault-name "${KEY_VAULT_NAME}" --name "minio-root-password" --value "${MINIO_ROOT_PASSWORD}" --output none
[[ -n "${MCP_BRIDGE_AUTH_TOKEN:-}" ]] && az keyvault secret set --vault-name "${KEY_VAULT_NAME}" --name "mcp-bridge-auth-token" --value "${MCP_BRIDGE_AUTH_TOKEN}" --output none

AOAI_ENDPOINT="https://${AOAI_ACCOUNT_NAME}.openai.azure.com/"
az keyvault secret set --vault-name "${KEY_VAULT_NAME}" --name "azure-openai-endpoint" --value "${AOAI_ENDPOINT}" --output none
[[ -n "${AZURE_OPENAI_API_KEY:-}" ]] && az keyvault secret set --vault-name "${KEY_VAULT_NAME}" --name "azure-openai-api-key" --value "${AZURE_OPENAI_API_KEY}" --output none
[[ -n "${AZURE_OPENAI_API_VERSION:-}" ]] && az keyvault secret set --vault-name "${KEY_VAULT_NAME}" --name "azure-openai-api-version" --value "${AZURE_OPENAI_API_VERSION}" --output none

echo "[infra] foundation deployment complete"
