#!/usr/bin/env bash
set -euo pipefail

AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-rg-workcore-prod-uaen}"
SWA_NAME="${SWA_NAME:-swa-workcore-prod-uaen}"
KEY_VAULT_NAME="${KEY_VAULT_NAME:-kv-workcore-prod-uaen}"

WORKCORE_DOMAIN="${WORKCORE_DOMAIN:-}"
ENTRA_APP_NAME="${ENTRA_APP_NAME:-workcore-builder-swa}"
CREATE_ENTRA_APP="${CREATE_ENTRA_APP:-false}"

AZURE_TENANT_ID="${AZURE_TENANT_ID:-}"
ENTRA_CLIENT_ID="${ENTRA_CLIENT_ID:-}"
ENTRA_CLIENT_SECRET="${ENTRA_CLIENT_SECRET:-}"

is_true() {
  local value
  value="$(echo "${1:-}" | tr '[:upper:]' '[:lower:]')"
  [[ "${value}" == "1" || "${value}" == "true" || "${value}" == "yes" || "${value}" == "on" ]]
}

if [[ -z "${AZURE_TENANT_ID}" ]]; then
  AZURE_TENANT_ID="$(az account show --query tenantId -o tsv)"
fi

SWA_DEFAULT_HOST="$(
  az staticwebapp show \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --name "${SWA_NAME}" \
    --query defaultHostname \
    -o tsv
)"

REDIRECT_URIS=(
  "https://${SWA_DEFAULT_HOST}/.auth/login/aad/callback"
)
if [[ -n "${WORKCORE_DOMAIN}" ]]; then
  REDIRECT_URIS+=("https://${WORKCORE_DOMAIN}/.auth/login/aad/callback")
fi

if is_true "${CREATE_ENTRA_APP}"; then
  if [[ -z "${ENTRA_CLIENT_ID}" ]]; then
    ENTRA_CLIENT_ID="$(az ad app list --display-name "${ENTRA_APP_NAME}" --query '[0].appId' -o tsv)"
  fi

  if [[ -z "${ENTRA_CLIENT_ID}" ]]; then
    ENTRA_CLIENT_ID="$(
      az ad app create \
        --display-name "${ENTRA_APP_NAME}" \
        --sign-in-audience AzureADMyOrg \
        --web-redirect-uris "${REDIRECT_URIS[@]}" \
        --query appId \
        -o tsv
    )"
  else
    az ad app update \
      --id "${ENTRA_CLIENT_ID}" \
      --web-redirect-uris "${REDIRECT_URIS[@]}" \
      --output none
  fi

  if [[ -z "${ENTRA_CLIENT_SECRET}" ]]; then
    ENTRA_CLIENT_SECRET="$(
      az ad app credential reset \
        --id "${ENTRA_CLIENT_ID}" \
        --append \
        --display-name "swa-client-secret" \
        --years 1 \
        --query password \
        -o tsv
    )"
  fi
fi

if [[ -z "${ENTRA_CLIENT_ID}" || -z "${ENTRA_CLIENT_SECRET}" || -z "${AZURE_TENANT_ID}" ]]; then
  echo "ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET and AZURE_TENANT_ID are required." >&2
  echo "Set CREATE_ENTRA_APP=true to create app/secret automatically if your account has Entra app permissions." >&2
  exit 1
fi

az staticwebapp appsettings set \
  --resource-group "${AZ_RESOURCE_GROUP}" \
  --name "${SWA_NAME}" \
  --setting-names \
    AZURE_CLIENT_ID="${ENTRA_CLIENT_ID}" \
    AZURE_CLIENT_SECRET="${ENTRA_CLIENT_SECRET}" \
    AZURE_TENANT_ID="${AZURE_TENANT_ID}" \
  --output none

if [[ -n "${KEY_VAULT_NAME}" ]]; then
  az keyvault secret set --vault-name "${KEY_VAULT_NAME}" --name "swa-entra-client-id" --value "${ENTRA_CLIENT_ID}" --output none
  az keyvault secret set --vault-name "${KEY_VAULT_NAME}" --name "swa-entra-client-secret" --value "${ENTRA_CLIENT_SECRET}" --output none
  az keyvault secret set --vault-name "${KEY_VAULT_NAME}" --name "swa-entra-tenant-id" --value "${AZURE_TENANT_ID}" --output none
fi

echo "[swa-auth] configured Entra provider settings for ${SWA_NAME}"
echo "[swa-auth] tenant: ${AZURE_TENANT_ID}"
echo "[swa-auth] client-id: ${ENTRA_CLIENT_ID}"
