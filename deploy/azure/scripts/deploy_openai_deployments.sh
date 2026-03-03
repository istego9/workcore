#!/usr/bin/env bash
set -euo pipefail

AZ_LOCATION="${AZ_LOCATION:-uaenorth}"
AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-rg-workcore-prod-uaen}"
AOAI_ACCOUNT_NAME="${AOAI_ACCOUNT_NAME:-aoai-workcore-prod-uaen}"

WF_AGENT_DEPLOYMENT="${WF_AGENT_DEPLOYMENT:-wf-agent}"
WF_AGENT_MODEL_NAME="${WF_AGENT_MODEL_NAME:-OpenAI.gpt-5-chat}"

WF_ROUTER_DEPLOYMENT="${WF_ROUTER_DEPLOYMENT:-wf-router}"
WF_ROUTER_MODEL_NAME="${WF_ROUTER_MODEL_NAME:-OpenAI.gpt-5-mini}"

WF_STT_DEPLOYMENT="${WF_STT_DEPLOYMENT:-wf-stt}"
WF_STT_MODEL_NAME="${WF_STT_MODEL_NAME:-OpenAI.whisper.001}"

resolve_latest_model_version() {
  local model_name="$1"
  local version
  version="$(az cognitiveservices model list -l "${AZ_LOCATION}" --query "[?name=='${model_name}'] | sort_by(@,&version) | [-1].version" -o tsv)"
  if [[ -z "${version}" || "${version}" == "null" ]]; then
    echo "Unable to resolve model version for ${model_name} in ${AZ_LOCATION}" >&2
    exit 1
  fi
  echo "${version}"
}

upsert_deployment() {
  local deployment_name="$1"
  local model_name="$2"
  local model_version="$3"

  if az cognitiveservices account deployment show \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --name "${AOAI_ACCOUNT_NAME}" \
    --deployment-name "${deployment_name}" >/dev/null 2>&1; then
    echo "[aoai] deployment ${deployment_name} already exists, skipping"
    return
  fi

  echo "[aoai] creating deployment ${deployment_name} -> ${model_name}@${model_version}"
  az cognitiveservices account deployment create \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --name "${AOAI_ACCOUNT_NAME}" \
    --deployment-name "${deployment_name}" \
    --model-format OpenAI \
    --model-name "${model_name}" \
    --model-version "${model_version}" \
    --sku-name Standard \
    --sku-capacity 1 \
    --output none
}

AGENT_VERSION="${WF_AGENT_MODEL_VERSION:-$(resolve_latest_model_version "${WF_AGENT_MODEL_NAME}")}"
ROUTER_VERSION="${WF_ROUTER_MODEL_VERSION:-$(resolve_latest_model_version "${WF_ROUTER_MODEL_NAME}")}"
STT_VERSION="${WF_STT_MODEL_VERSION:-$(resolve_latest_model_version "${WF_STT_MODEL_NAME}")}"

upsert_deployment "${WF_AGENT_DEPLOYMENT}" "${WF_AGENT_MODEL_NAME}" "${AGENT_VERSION}"
upsert_deployment "${WF_ROUTER_DEPLOYMENT}" "${WF_ROUTER_MODEL_NAME}" "${ROUTER_VERSION}"
upsert_deployment "${WF_STT_DEPLOYMENT}" "${WF_STT_MODEL_NAME}" "${STT_VERSION}"

echo "[aoai] deployments ready"
