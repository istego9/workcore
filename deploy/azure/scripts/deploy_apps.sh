#!/usr/bin/env bash
set -euo pipefail

AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-rg-workcore-prod-uaen}"
AZ_LOCATION="${AZ_LOCATION:-uaenorth}"
ACA_ENV_NAME="${ACA_ENV_NAME:-cae-workcore-prod-uaen}"
ACR_NAME="${ACR_NAME:-acrworkcoreproduaen}"
KEY_VAULT_NAME="${KEY_VAULT_NAME:-kv-workcore-prod-uaen}"
STORAGE_ACCOUNT_NAME="${STORAGE_ACCOUNT_NAME:-stworkcoreproduaen}"
MINIO_SHARE_NAME="${MINIO_SHARE_NAME:-minio-data}"

ORCHESTRATOR_APP_NAME="${ORCHESTRATOR_APP_NAME:-ca-orchestrator}"
CHATKIT_APP_NAME="${CHATKIT_APP_NAME:-ca-chatkit}"
MCP_BRIDGE_APP_NAME="${MCP_BRIDGE_APP_NAME:-ca-mcp-bridge}"
MINIO_APP_NAME="${MINIO_APP_NAME:-ca-minio}"
MIGRATE_JOB_NAME="${MIGRATE_JOB_NAME:-caj-migrate-workcore}"

WORKCORE_IMAGE="${WORKCORE_IMAGE:-}"
if [[ -z "${WORKCORE_IMAGE}" ]]; then
  echo "WORKCORE_IMAGE is required (example: <acr>/workcore-orchestrator:<tag>)" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

ACA_ENV_ID="$(az containerapp env show --resource-group "${AZ_RESOURCE_GROUP}" --name "${ACA_ENV_NAME}" --query id -o tsv)"
ACR_LOGIN_SERVER="$(az acr show --resource-group "${AZ_RESOURCE_GROUP}" --name "${ACR_NAME}" --query loginServer -o tsv)"
ACR_USERNAME="$(az acr credential show --resource-group "${AZ_RESOURCE_GROUP}" --name "${ACR_NAME}" --query username -o tsv)"
ACR_PASSWORD="$(az acr credential show --resource-group "${AZ_RESOURCE_GROUP}" --name "${ACR_NAME}" --query "passwords[0].value" -o tsv)"

get_secret_or_default() {
  local secret_name="$1"
  local default_value="${2:-}"
  local value
  value="$(az keyvault secret show --vault-name "${KEY_VAULT_NAME}" --name "${secret_name}" --query value -o tsv 2>/dev/null || true)"
  if [[ -z "${value}" ]]; then
    value="${default_value}"
  fi
  echo "${value}"
}

DATABASE_URL="$(get_secret_or_default workcore-database-url)"
CHATKIT_DATABASE_URL="$(get_secret_or_default chatkit-database-url "${DATABASE_URL}")"
WORKCORE_API_AUTH_TOKEN="$(get_secret_or_default workcore-api-auth-token)"
WEBHOOK_DEFAULT_INBOUND_SECRET="$(get_secret_or_default webhook-default-inbound-secret)"
CHATKIT_AUTH_TOKEN="$(get_secret_or_default chatkit-auth-token)"
MINIO_ROOT_USER="$(get_secret_or_default minio-root-user)"
MINIO_ROOT_PASSWORD="$(get_secret_or_default minio-root-password)"
MCP_BRIDGE_AUTH_TOKEN="$(get_secret_or_default mcp-bridge-auth-token)"
AZURE_OPENAI_ENDPOINT="$(get_secret_or_default azure-openai-endpoint)"
AZURE_OPENAI_API_KEY="$(get_secret_or_default azure-openai-api-key)"
AZURE_OPENAI_API_VERSION="$(get_secret_or_default azure-openai-api-version 2025-01-01-preview)"

require_non_empty() {
  local value="$1"
  local label="$2"
  if [[ -z "${value}" ]]; then
    echo "${label} is required (missing Key Vault secret)" >&2
    exit 1
  fi
}

if [[ -z "${DATABASE_URL}" ]]; then
  echo "workcore-database-url secret is required in Key Vault ${KEY_VAULT_NAME}" >&2
  exit 1
fi
require_non_empty "${WORKCORE_API_AUTH_TOKEN}" "workcore-api-auth-token"
require_non_empty "${WEBHOOK_DEFAULT_INBOUND_SECRET}" "webhook-default-inbound-secret"
require_non_empty "${CHATKIT_AUTH_TOKEN}" "chatkit-auth-token"
require_non_empty "${MINIO_ROOT_USER}" "minio-root-user"
require_non_empty "${MINIO_ROOT_PASSWORD}" "minio-root-password"
require_non_empty "${MCP_BRIDGE_AUTH_TOKEN}" "mcp-bridge-auth-token"
if [[ -z "${AZURE_OPENAI_ENDPOINT}" || -z "${AZURE_OPENAI_API_KEY}" || -z "${AZURE_OPENAI_API_VERSION}" ]]; then
  echo "Azure OpenAI secrets are required: azure-openai-endpoint, azure-openai-api-key, azure-openai-api-version" >&2
  exit 1
fi

# Configure Azure Files storage for MinIO durable volume.
STORAGE_ACCOUNT_KEY="$(az storage account keys list --resource-group "${AZ_RESOURCE_GROUP}" --account-name "${STORAGE_ACCOUNT_NAME}" --query "[0].value" -o tsv)"
az containerapp env storage set \
  --resource-group "${AZ_RESOURCE_GROUP}" \
  --name "${ACA_ENV_NAME}" \
  --storage-name miniofiles \
  --access-mode ReadWrite \
  --azure-file-account-name "${STORAGE_ACCOUNT_NAME}" \
  --azure-file-account-key "${STORAGE_ACCOUNT_KEY}" \
  --azure-file-share-name "${MINIO_SHARE_NAME}" \
  --output none

write_manifest() {
  local path="$1"
  cat > "${path}"
}

write_manifest "${TMP_DIR}/mcp-bridge.yaml" <<EOF_MCP
name: ${MCP_BRIDGE_APP_NAME}
type: Microsoft.App/containerApps
location: ${AZ_LOCATION}
properties:
  managedEnvironmentId: ${ACA_ENV_ID}
  configuration:
    activeRevisionsMode: Single
    ingress:
      external: false
      targetPort: 8002
      transport: auto
    registries:
      - server: ${ACR_LOGIN_SERVER}
        username: ${ACR_USERNAME}
        passwordSecretRef: acr-password
    secrets:
      - name: acr-password
        value: ${ACR_PASSWORD}
      - name: mcp-bridge-auth-token
        value: ${MCP_BRIDGE_AUTH_TOKEN}
  template:
    containers:
      - name: mcp-bridge
        image: ${WORKCORE_IMAGE}
        command:
          - uvicorn
          - apps.orchestrator.mcp_bridge.service:app
          - --host
          - 0.0.0.0
          - --port
          - "8002"
        env:
          - name: MCP_BRIDGE_AUTH_TOKEN
            secretRef: mcp-bridge-auth-token
        resources:
          cpu: 0.5
          memory: 1Gi
    scale:
      minReplicas: 1
      maxReplicas: 1
EOF_MCP

write_manifest "${TMP_DIR}/minio.yaml" <<EOF_MINIO
name: ${MINIO_APP_NAME}
type: Microsoft.App/containerApps
location: ${AZ_LOCATION}
properties:
  managedEnvironmentId: ${ACA_ENV_ID}
  configuration:
    activeRevisionsMode: Single
    ingress:
      external: false
      targetPort: 9000
      transport: auto
    secrets:
      - name: minio-root-user
        value: ${MINIO_ROOT_USER}
      - name: minio-root-password
        value: ${MINIO_ROOT_PASSWORD}
  template:
    containers:
      - name: minio
        image: minio/minio:latest
        command:
          - minio
        args:
          - server
          - /data
          - --console-address
          - :9001
        env:
          - name: MINIO_ROOT_USER
            secretRef: minio-root-user
          - name: MINIO_ROOT_PASSWORD
            secretRef: minio-root-password
        resources:
          cpu: 0.5
          memory: 1Gi
        volumeMounts:
          - volumeName: minio-data
            mountPath: /data
    volumes:
      - name: minio-data
        storageType: AzureFile
        storageName: miniofiles
    scale:
      minReplicas: 1
      maxReplicas: 1
EOF_MINIO

apply_container_app() {
  local name="$1"
  local manifest="$2"
  if az containerapp show --resource-group "${AZ_RESOURCE_GROUP}" --name "${name}" >/dev/null 2>&1; then
    az containerapp update --resource-group "${AZ_RESOURCE_GROUP}" --name "${name}" --yaml "${manifest}" --output none
  else
    az containerapp create --resource-group "${AZ_RESOURCE_GROUP}" --yaml "${manifest}" --output none
  fi
}

echo "[apps] deploying internal services"
apply_container_app "${MCP_BRIDGE_APP_NAME}" "${TMP_DIR}/mcp-bridge.yaml"
apply_container_app "${MINIO_APP_NAME}" "${TMP_DIR}/minio.yaml"

MCP_BRIDGE_FQDN="$(az containerapp show --resource-group "${AZ_RESOURCE_GROUP}" --name "${MCP_BRIDGE_APP_NAME}" --query properties.configuration.ingress.fqdn -o tsv)"
MINIO_FQDN="$(az containerapp show --resource-group "${AZ_RESOURCE_GROUP}" --name "${MINIO_APP_NAME}" --query properties.configuration.ingress.fqdn -o tsv)"
MCP_BRIDGE_BASE_URL="https://${MCP_BRIDGE_FQDN}"
MINIO_ENDPOINT="${MINIO_FQDN}"

write_manifest "${TMP_DIR}/orchestrator.yaml" <<EOF_ORCH
name: ${ORCHESTRATOR_APP_NAME}
type: Microsoft.App/containerApps
location: ${AZ_LOCATION}
properties:
  managedEnvironmentId: ${ACA_ENV_ID}
  configuration:
    activeRevisionsMode: Single
    ingress:
      external: true
      targetPort: 8000
      transport: auto
    registries:
      - server: ${ACR_LOGIN_SERVER}
        username: ${ACR_USERNAME}
        passwordSecretRef: acr-password
    secrets:
      - name: acr-password
        value: ${ACR_PASSWORD}
      - name: db-url
        value: ${DATABASE_URL}
      - name: api-auth-token
        value: ${WORKCORE_API_AUTH_TOKEN}
      - name: webhook-inbound-secret
        value: ${WEBHOOK_DEFAULT_INBOUND_SECRET}
      - name: azure-openai-api-key
        value: ${AZURE_OPENAI_API_KEY}
      - name: mcp-bridge-auth-token
        value: ${MCP_BRIDGE_AUTH_TOKEN}
  template:
    containers:
      - name: orchestrator
        image: ${WORKCORE_IMAGE}
        command:
          - uvicorn
          - apps.orchestrator.api.service:app
          - --host
          - 0.0.0.0
          - --port
          - "8000"
        env:
          - name: DATABASE_URL
            secretRef: db-url
          - name: CHATKIT_DATABASE_URL
            secretRef: db-url
          - name: WORKCORE_API_AUTH_TOKEN
            secretRef: api-auth-token
          - name: WEBHOOK_DEFAULT_INBOUND_SECRET
            secretRef: webhook-inbound-secret
          - name: WEBHOOK_DEFAULT_INTEGRATION_KEY
            value: default
          - name: CORS_ALLOW_ORIGINS
            value: https://workcore.example.com,https://api.example.com,https://chatkit.example.com
          - name: INTEGRATION_HTTP_ALLOWED_HOSTS
            value: api.openai.com,*.openai.azure.com
          - name: STREAMING_STORE_BACKEND
            value: postgres
          - name: WEBHOOK_STORE_BACKEND
            value: postgres
          - name: STREAMING_BACKEND
            value: memory
          - name: AGENT_EXECUTOR_MODE
            value: live
          - name: OPENAI_API
            value: responses
          - name: OPENAI_MODEL
            value: wf-agent
          - name: ORCHESTRATOR_MODEL_ID
            value: wf-router
          - name: AZURE_OPENAI_ENDPOINT
            value: ${AZURE_OPENAI_ENDPOINT}
          - name: AZURE_OPENAI_API_VERSION
            value: ${AZURE_OPENAI_API_VERSION}
          - name: AZURE_OPENAI_API_KEY
            secretRef: azure-openai-api-key
          - name: MCP_BRIDGE_BASE_URL
            value: ${MCP_BRIDGE_BASE_URL}
          - name: MCP_BRIDGE_AUTH_TOKEN
            secretRef: mcp-bridge-auth-token
        resources:
          cpu: 1.0
          memory: 2Gi
    scale:
      minReplicas: 1
      maxReplicas: 1
EOF_ORCH

write_manifest "${TMP_DIR}/chatkit.yaml" <<EOF_CHATKIT
name: ${CHATKIT_APP_NAME}
type: Microsoft.App/containerApps
location: ${AZ_LOCATION}
properties:
  managedEnvironmentId: ${ACA_ENV_ID}
  configuration:
    activeRevisionsMode: Single
    ingress:
      external: true
      targetPort: 8001
      transport: auto
    registries:
      - server: ${ACR_LOGIN_SERVER}
        username: ${ACR_USERNAME}
        passwordSecretRef: acr-password
    secrets:
      - name: acr-password
        value: ${ACR_PASSWORD}
      - name: db-url
        value: ${CHATKIT_DATABASE_URL}
      - name: chatkit-auth-token
        value: ${CHATKIT_AUTH_TOKEN}
      - name: minio-root-user
        value: ${MINIO_ROOT_USER}
      - name: minio-root-password
        value: ${MINIO_ROOT_PASSWORD}
      - name: azure-openai-api-key
        value: ${AZURE_OPENAI_API_KEY}
      - name: mcp-bridge-auth-token
        value: ${MCP_BRIDGE_AUTH_TOKEN}
  template:
    containers:
      - name: chatkit
        image: ${WORKCORE_IMAGE}
        command:
          - uvicorn
          - apps.orchestrator.chatkit.service:app
          - --host
          - 0.0.0.0
          - --port
          - "8001"
        env:
          - name: CHATKIT_DATABASE_URL
            secretRef: db-url
          - name: CHATKIT_AUTH_TOKEN
            secretRef: chatkit-auth-token
          - name: CHATKIT_OBJECT_ENDPOINT
            value: ${MINIO_ENDPOINT}
          - name: CHATKIT_OBJECT_ACCESS_KEY
            secretRef: minio-root-user
          - name: CHATKIT_OBJECT_SECRET_KEY
            secretRef: minio-root-password
          - name: CHATKIT_OBJECT_BUCKET
            value: chatkit
          - name: CHATKIT_OBJECT_SECURE
            value: "true"
          - name: CHATKIT_OBJECT_PREFIX
            value: chatkit
          - name: CHATKIT_OBJECT_CREATE_BUCKET
            value: "true"
          - name: CHATKIT_STT_MODEL
            value: wf-stt
          - name: CHATKIT_STT_API_KEY
            secretRef: azure-openai-api-key
          - name: AZURE_OPENAI_ENDPOINT
            value: ${AZURE_OPENAI_ENDPOINT}
          - name: AZURE_OPENAI_API_VERSION
            value: ${AZURE_OPENAI_API_VERSION}
          - name: AZURE_OPENAI_API_KEY
            secretRef: azure-openai-api-key
          - name: MCP_BRIDGE_BASE_URL
            value: ${MCP_BRIDGE_BASE_URL}
          - name: MCP_BRIDGE_AUTH_TOKEN
            secretRef: mcp-bridge-auth-token
          - name: CORS_ALLOW_ORIGINS
            value: https://workcore.example.com,https://api.example.com,https://chatkit.example.com
        resources:
          cpu: 1.0
          memory: 2Gi
    scale:
      minReplicas: 1
      maxReplicas: 1
EOF_CHATKIT

echo "[apps] deploying orchestrator/chatkit"
apply_container_app "${ORCHESTRATOR_APP_NAME}" "${TMP_DIR}/orchestrator.yaml"
apply_container_app "${CHATKIT_APP_NAME}" "${TMP_DIR}/chatkit.yaml"

write_manifest "${TMP_DIR}/migrate-job.yaml" <<EOF_JOB
name: ${MIGRATE_JOB_NAME}
type: Microsoft.App/jobs
location: ${AZ_LOCATION}
properties:
  environmentId: ${ACA_ENV_ID}
  configuration:
    triggerType: Manual
    replicaRetryLimit: 1
    replicaTimeout: 900
    secrets:
      - name: acr-password
        value: ${ACR_PASSWORD}
      - name: db-url
        value: ${DATABASE_URL}
    registries:
      - server: ${ACR_LOGIN_SERVER}
        username: ${ACR_USERNAME}
        passwordSecretRef: acr-password
  template:
    containers:
      - name: migrate
        image: ${WORKCORE_IMAGE}
        command:
          - python
          - scripts/migrate.py
        env:
          - name: DATABASE_URL
            secretRef: db-url
    initContainers: []
EOF_JOB

if az containerapp job show --resource-group "${AZ_RESOURCE_GROUP}" --name "${MIGRATE_JOB_NAME}" >/dev/null 2>&1; then
  az containerapp job update --resource-group "${AZ_RESOURCE_GROUP}" --name "${MIGRATE_JOB_NAME}" --yaml "${TMP_DIR}/migrate-job.yaml" --output none
else
  az containerapp job create --resource-group "${AZ_RESOURCE_GROUP}" --yaml "${TMP_DIR}/migrate-job.yaml" --output none
fi

echo "[apps] running migration job"
az containerapp job start --resource-group "${AZ_RESOURCE_GROUP}" --name "${MIGRATE_JOB_NAME}" --output none

echo "[apps] deployment complete"
