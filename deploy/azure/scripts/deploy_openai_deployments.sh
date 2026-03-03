#!/usr/bin/env bash
set -euo pipefail

AZ_LOCATION="${AZ_LOCATION:-uaenorth}"
AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-rg-workcore-prod-uaen}"
AOAI_ACCOUNT_NAME="${AOAI_ACCOUNT_NAME:-aoai-workcore-prod-uaen}"

WF_AGENT_DEPLOYMENT="${WF_AGENT_DEPLOYMENT:-wf-agent}"
WF_AGENT_MODEL_NAME="${WF_AGENT_MODEL_NAME:-gpt-5-chat}"

WF_ROUTER_DEPLOYMENT="${WF_ROUTER_DEPLOYMENT:-wf-router}"
WF_ROUTER_MODEL_NAME="${WF_ROUTER_MODEL_NAME:-gpt-5-mini}"

WF_STT_DEPLOYMENT="${WF_STT_DEPLOYMENT:-wf-stt}"
WF_STT_MODEL_NAME="${WF_STT_MODEL_NAME:-whisper}"
WF_STT_MODEL_VERSION="${WF_STT_MODEL_VERSION:-001}"

resolve_latest_model_version() {
  local model_name="$1"
  local version
  version="$(az cognitiveservices model list -l "${AZ_LOCATION}" --query "[?model.name=='${model_name}'] | sort_by(@,&model.version) | [-1].model.version" -o tsv)"
  if [[ -z "${version}" || "${version}" == "null" ]]; then
    echo "Unable to resolve model version for ${model_name} in ${AZ_LOCATION}" >&2
    exit 1
  fi
  echo "${version}"
}

resolve_model_sku_name() {
  local model_name="$1"
  local model_version="$2"
  local sku_name
  sku_name="$(az cognitiveservices model list -l "${AZ_LOCATION}" --query "[?model.name=='${model_name}' && model.version=='${model_version}'] | [0].model.skus[0].name" -o tsv)"
  if [[ -z "${sku_name}" || "${sku_name}" == "null" ]]; then
    echo "Unable to resolve sku name for ${model_name}@${model_version} in ${AZ_LOCATION}" >&2
    exit 1
  fi
  echo "${sku_name}"
}

resolve_model_sku_capacity() {
  local model_name="$1"
  local model_version="$2"
  local capacity
  capacity="$(az cognitiveservices model list -l "${AZ_LOCATION}" --query "[?model.name=='${model_name}' && model.version=='${model_version}'] | [0].model.skus[0].capacity.default" -o tsv)"
  if [[ -z "${capacity}" || "${capacity}" == "null" ]]; then
    echo "1"
    return
  fi
  echo "${capacity}"
}

upsert_deployment() {
  local deployment_name="$1"
  local model_name="$2"
  local model_version="$3"
  local sku_name="$4"
  local sku_capacity="$5"

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
    --sku-name "${sku_name}" \
    --sku-capacity "${sku_capacity}" \
    --output none
}

AGENT_VERSION="${WF_AGENT_MODEL_VERSION:-$(resolve_latest_model_version "${WF_AGENT_MODEL_NAME}")}"
ROUTER_VERSION="${WF_ROUTER_MODEL_VERSION:-$(resolve_latest_model_version "${WF_ROUTER_MODEL_NAME}")}"
STT_VERSION="${WF_STT_MODEL_VERSION:-$(resolve_latest_model_version "${WF_STT_MODEL_NAME}")}"

AGENT_SKU_NAME="${WF_AGENT_SKU_NAME:-$(resolve_model_sku_name "${WF_AGENT_MODEL_NAME}" "${AGENT_VERSION}")}"
ROUTER_SKU_NAME="${WF_ROUTER_SKU_NAME:-$(resolve_model_sku_name "${WF_ROUTER_MODEL_NAME}" "${ROUTER_VERSION}")}"
STT_SKU_NAME="${WF_STT_SKU_NAME:-$(resolve_model_sku_name "${WF_STT_MODEL_NAME}" "${STT_VERSION}")}"

AGENT_SKU_CAPACITY="${WF_AGENT_SKU_CAPACITY:-$(resolve_model_sku_capacity "${WF_AGENT_MODEL_NAME}" "${AGENT_VERSION}")}"
ROUTER_SKU_CAPACITY="${WF_ROUTER_SKU_CAPACITY:-$(resolve_model_sku_capacity "${WF_ROUTER_MODEL_NAME}" "${ROUTER_VERSION}")}"
STT_SKU_CAPACITY="${WF_STT_SKU_CAPACITY:-$(resolve_model_sku_capacity "${WF_STT_MODEL_NAME}" "${STT_VERSION}")}"

upsert_deployment "${WF_AGENT_DEPLOYMENT}" "${WF_AGENT_MODEL_NAME}" "${AGENT_VERSION}" "${AGENT_SKU_NAME}" "${AGENT_SKU_CAPACITY}"
upsert_deployment "${WF_ROUTER_DEPLOYMENT}" "${WF_ROUTER_MODEL_NAME}" "${ROUTER_VERSION}" "${ROUTER_SKU_NAME}" "${ROUTER_SKU_CAPACITY}"
upsert_deployment "${WF_STT_DEPLOYMENT}" "${WF_STT_MODEL_NAME}" "${STT_VERSION}" "${STT_SKU_NAME}" "${STT_SKU_CAPACITY}"

echo "[aoai] deployments ready"
