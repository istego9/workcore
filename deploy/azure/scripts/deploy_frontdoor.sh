#!/usr/bin/env bash
set -euo pipefail

AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-rg-workcore-prod-uaen}"
AFD_PROFILE_NAME="${AFD_PROFILE_NAME:-afd-workcore-prod-uaen}"
AFD_ENDPOINT_NAME="${AFD_ENDPOINT_NAME:-workcore}"
WAF_POLICY_NAME="${WAF_POLICY_NAME:-waf-workcore-prod-uaen}"
SECURITY_POLICY_NAME="${SECURITY_POLICY_NAME:-sp-workcore-prod-uaen}"

SWA_NAME="${SWA_NAME:-swa-workcore-prod-uaen}"
ORCHESTRATOR_APP_NAME="${ORCHESTRATOR_APP_NAME:-ca-orchestrator}"
CHATKIT_APP_NAME="${CHATKIT_APP_NAME:-ca-chatkit}"

WORKCORE_DOMAIN="${WORKCORE_DOMAIN:-}"
API_DOMAIN="${API_DOMAIN:-}"
CHATKIT_DOMAIN="${CHATKIT_DOMAIN:-}"

ensure_profile() {
  if az afd profile show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" >/dev/null 2>&1; then
    return
  fi
  az afd profile create \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --profile-name "${AFD_PROFILE_NAME}" \
    --sku Standard_AzureFrontDoor \
    --output none
}

ensure_endpoint() {
  if az afd endpoint show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --endpoint-name "${AFD_ENDPOINT_NAME}" >/dev/null 2>&1; then
    return
  fi
  az afd endpoint create \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --profile-name "${AFD_PROFILE_NAME}" \
    --endpoint-name "${AFD_ENDPOINT_NAME}" \
    --enabled-state Enabled \
    --output none
}

ensure_origin_group() {
  local origin_group_name="$1"
  local probe_path="$2"
  if az afd origin-group show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --origin-group-name "${origin_group_name}" >/dev/null 2>&1; then
    return
  fi
  az afd origin-group create \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --profile-name "${AFD_PROFILE_NAME}" \
    --origin-group-name "${origin_group_name}" \
    --probe-request-type GET \
    --probe-protocol Https \
    --probe-path "${probe_path}" \
    --sample-size 4 \
    --successful-samples-required 3 \
    --additional-latency-in-milliseconds 0 \
    --output none
}

ensure_origin() {
  local origin_group_name="$1"
  local origin_name="$2"
  local host_name="$3"
  if az afd origin show \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --profile-name "${AFD_PROFILE_NAME}" \
    --origin-group-name "${origin_group_name}" \
    --origin-name "${origin_name}" >/dev/null 2>&1; then
    return
  fi
  az afd origin create \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --profile-name "${AFD_PROFILE_NAME}" \
    --origin-group-name "${origin_group_name}" \
    --origin-name "${origin_name}" \
    --host-name "${host_name}" \
    --origin-host-header "${host_name}" \
    --http-port 80 \
    --https-port 443 \
    --priority 1 \
    --weight 1000 \
    --enabled-state Enabled \
    --output none
}

ensure_route() {
  local route_name="$1"
  local origin_group_name="$2"
  local custom_domain_name="$3"

  if az afd route show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --endpoint-name "${AFD_ENDPOINT_NAME}" --route-name "${route_name}" >/dev/null 2>&1; then
    return
  fi

  if [[ -n "${custom_domain_name}" ]]; then
    az afd route create \
      --resource-group "${AZ_RESOURCE_GROUP}" \
      --profile-name "${AFD_PROFILE_NAME}" \
      --endpoint-name "${AFD_ENDPOINT_NAME}" \
      --route-name "${route_name}" \
      --origin-group "${origin_group_name}" \
      --supported-protocols Http Https \
      --patterns-to-match '/*' \
      --forwarding-protocol HttpsOnly \
      --https-redirect Enabled \
      --link-to-default-domain Disabled \
      --custom-domains "${custom_domain_name}" \
      --enabled-state Enabled \
      --output none
  else
    az afd route create \
      --resource-group "${AZ_RESOURCE_GROUP}" \
      --profile-name "${AFD_PROFILE_NAME}" \
      --endpoint-name "${AFD_ENDPOINT_NAME}" \
      --route-name "${route_name}" \
      --origin-group "${origin_group_name}" \
      --supported-protocols Http Https \
      --patterns-to-match '/*' \
      --forwarding-protocol HttpsOnly \
      --https-redirect Enabled \
      --link-to-default-domain Enabled \
      --enabled-state Enabled \
      --output none
  fi
}

ensure_custom_domain() {
  local custom_domain_name="$1"
  local host_name="$2"
  if az afd custom-domain show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --custom-domain-name "${custom_domain_name}" >/dev/null 2>&1; then
    return
  fi
  az afd custom-domain create \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --profile-name "${AFD_PROFILE_NAME}" \
    --custom-domain-name "${custom_domain_name}" \
    --host-name "${host_name}" \
    --certificate-type ManagedCertificate \
    --minimum-tls-version TLS12 \
    --output none
}

ensure_waf_and_security_policy() {
  if ! az afd waf-policy show --resource-group "${AZ_RESOURCE_GROUP}" --policy-name "${WAF_POLICY_NAME}" >/dev/null 2>&1; then
    az afd waf-policy create \
      --resource-group "${AZ_RESOURCE_GROUP}" \
      --policy-name "${WAF_POLICY_NAME}" \
      --sku Standard_AzureFrontDoor \
      --mode Prevention \
      --output none
  fi

  if az afd security-policy show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --security-policy-name "${SECURITY_POLICY_NAME}" >/dev/null 2>&1; then
    return
  fi

  local waf_policy_id
  waf_policy_id="$(az afd waf-policy show --resource-group "${AZ_RESOURCE_GROUP}" --policy-name "${WAF_POLICY_NAME}" --query id -o tsv)"

  local domains=()
  if [[ -n "${WORKCORE_DOMAIN}" && -n "${API_DOMAIN}" && -n "${CHATKIT_DOMAIN}" ]]; then
    domains+=("$(az afd custom-domain show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --custom-domain-name cd-workcore --query id -o tsv)")
    domains+=("$(az afd custom-domain show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --custom-domain-name cd-api --query id -o tsv)")
    domains+=("$(az afd custom-domain show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --custom-domain-name cd-chatkit --query id -o tsv)")
  else
    domains+=("$(az afd endpoint show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --endpoint-name "${AFD_ENDPOINT_NAME}" --query id -o tsv)")
  fi

  az afd security-policy create \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --profile-name "${AFD_PROFILE_NAME}" \
    --security-policy-name "${SECURITY_POLICY_NAME}" \
    --waf-policy "${waf_policy_id}" \
    --domains "${domains[@]}" \
    --output none
}

echo "[afd] resolving app origin hostnames"
SWA_HOST="$(az staticwebapp show --resource-group "${AZ_RESOURCE_GROUP}" --name "${SWA_NAME}" --query defaultHostname -o tsv)"
API_HOST="$(az containerapp show --resource-group "${AZ_RESOURCE_GROUP}" --name "${ORCHESTRATOR_APP_NAME}" --query properties.configuration.ingress.fqdn -o tsv)"
CHATKIT_HOST="$(az containerapp show --resource-group "${AZ_RESOURCE_GROUP}" --name "${CHATKIT_APP_NAME}" --query properties.configuration.ingress.fqdn -o tsv)"

ensure_profile
ensure_endpoint

ensure_origin_group og-ui '/'
ensure_origin_group og-api '/health'
ensure_origin_group og-chatkit '/health'

ensure_origin og-ui origin-ui "${SWA_HOST}"
ensure_origin og-api origin-api "${API_HOST}"
ensure_origin og-chatkit origin-chatkit "${CHATKIT_HOST}"

if [[ -n "${WORKCORE_DOMAIN}" && -n "${API_DOMAIN}" && -n "${CHATKIT_DOMAIN}" ]]; then
  echo "[afd] configuring custom domains"
  ensure_custom_domain cd-workcore "${WORKCORE_DOMAIN}"
  ensure_custom_domain cd-api "${API_DOMAIN}"
  ensure_custom_domain cd-chatkit "${CHATKIT_DOMAIN}"

  ensure_route route-workcore og-ui cd-workcore
  ensure_route route-api og-api cd-api
  ensure_route route-chatkit og-chatkit cd-chatkit
else
  echo "[afd] custom domains not fully provided; configuring default-domain UI route only"
  ensure_route route-workcore og-ui ""
fi

ensure_waf_and_security_policy

echo "[afd] deployment complete"
