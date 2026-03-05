#!/usr/bin/env bash
set -euo pipefail

AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-rg-workcore-prod-uaen}"
AZ_LOCATION="${AZ_LOCATION:-uaenorth}"
AFD_PROFILE_NAME="${AFD_PROFILE_NAME:-afd-workcore-prod-uaen}"
AFD_ENDPOINT_NAME="${AFD_ENDPOINT_NAME:-workcore}"
WAF_POLICY_NAME="${WAF_POLICY_NAME:-waf-workcore-prod-uaen}"
SECURITY_POLICY_NAME="${SECURITY_POLICY_NAME:-sp-workcore-prod-uaen}"

SWA_NAME="${SWA_NAME:-swa-workcore-prod-uaen}"
ORCHESTRATOR_APP_NAME="${ORCHESTRATOR_APP_NAME:-ca-orchestrator}"
CHATKIT_APP_NAME="${CHATKIT_APP_NAME:-ca-chatkit}"
APIM_NAME="${APIM_NAME:-apim-workcore-prod-uaen}"

WORKCORE_DOMAIN="${WORKCORE_DOMAIN:-}"
CHATKIT_DOMAIN="${CHATKIT_DOMAIN:-}"
API_PRIMARY_DOMAIN="${API_PRIMARY_DOMAIN:-${API_DOMAIN:-}}"
API_SECONDARY_DOMAIN="${API_SECONDARY_DOMAIN:-}"
ENABLE_SECONDARY_API_DOMAIN="${ENABLE_SECONDARY_API_DOMAIN:-false}"
API_USE_APIM_GATEWAY="${API_USE_APIM_GATEWAY:-true}"
API_ROUTE_PATTERNS="${API_ROUTE_PATTERNS:-/health,/openapi.yaml,/api-reference,/workflow-authoring-guide,/schemas/*,/agent-integration-kit,/agent-integration-kit.json,/agent-integration-test,/agent-integration-test.json,/agent-integration-test/validate-draft,/agent-integration-logs,/projects,/projects/*,/capabilities,/capabilities/*,/orchestrator/*,/workflows,/workflows/*,/runs/*,/handoff/*,/webhooks/*,/artifacts/*}"

is_true() {
  local value
  value="$(echo "${1:-}" | tr '[:upper:]' '[:lower:]')"
  [[ "${value}" == "1" || "${value}" == "true" || "${value}" == "yes" || "${value}" == "on" ]]
}

upsert_profile() {
  if az afd profile show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" >/dev/null 2>&1; then
    return
  fi
  az afd profile create \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --profile-name "${AFD_PROFILE_NAME}" \
    --sku Standard_AzureFrontDoor \
    --output none
}

upsert_endpoint() {
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

upsert_origin_group() {
  local origin_group_name="$1"
  local probe_path="$2"
  if az afd origin-group show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --origin-group-name "${origin_group_name}" >/dev/null 2>&1; then
    az afd origin-group update \
      --resource-group "${AZ_RESOURCE_GROUP}" \
      --profile-name "${AFD_PROFILE_NAME}" \
      --origin-group-name "${origin_group_name}" \
      --enable-health-probe true \
      --probe-request-type GET \
      --probe-protocol Https \
      --probe-interval-in-seconds 120 \
      --probe-path "${probe_path}" \
      --sample-size 4 \
      --successful-samples-required 3 \
      --additional-latency-in-milliseconds 0 \
      --output none
    return
  fi

  az afd origin-group create \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --profile-name "${AFD_PROFILE_NAME}" \
    --origin-group-name "${origin_group_name}" \
    --enable-health-probe true \
    --probe-request-type GET \
    --probe-protocol Https \
    --probe-interval-in-seconds 120 \
    --probe-path "${probe_path}" \
    --sample-size 4 \
    --successful-samples-required 3 \
    --additional-latency-in-milliseconds 0 \
    --output none
}

upsert_origin() {
  local origin_group_name="$1"
  local origin_name="$2"
  local host_name="$3"

  if az afd origin show \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --profile-name "${AFD_PROFILE_NAME}" \
    --origin-group-name "${origin_group_name}" \
    --origin-name "${origin_name}" >/dev/null 2>&1; then
    az afd origin update \
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

upsert_custom_domain() {
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
    --no-wait \
    --minimum-tls-version TLS12 \
    --output none
}

wait_custom_domain_ready() {
  local custom_domain_name="$1"
  local max_attempts="${2:-60}"
  local sleep_seconds="${3:-10}"
  local attempt
  local state

  for ((attempt = 1; attempt <= max_attempts; attempt++)); do
    state="$(
      az afd custom-domain show \
        --resource-group "${AZ_RESOURCE_GROUP}" \
        --profile-name "${AFD_PROFILE_NAME}" \
        --custom-domain-name "${custom_domain_name}" \
        --query provisioningState \
        -o tsv 2>/dev/null || true
    )"
    if [[ "${state}" == "Succeeded" ]]; then
      return 0
    fi
    sleep "${sleep_seconds}"
  done

  echo "[afd] timeout waiting custom domain ${custom_domain_name} provisioningState=Succeeded" >&2
  return 1
}

upsert_route() {
  local route_name="$1"
  local origin_group_name="$2"
  local link_to_default_domain="$3"
  local patterns_csv="${4:-/*}"
  shift 4
  local custom_domains=("$@")
  local patterns=()
  IFS=',' read -r -a patterns <<< "${patterns_csv}"
  if [[ ${#patterns[@]} -eq 0 ]]; then
    patterns=('/*')
  fi

  local base_args=(
    --resource-group "${AZ_RESOURCE_GROUP}"
    --profile-name "${AFD_PROFILE_NAME}"
    --endpoint-name "${AFD_ENDPOINT_NAME}"
    --route-name "${route_name}"
    --origin-group "${origin_group_name}"
    --supported-protocols Http Https
    --patterns-to-match "${patterns[@]}"
    --forwarding-protocol HttpsOnly
    --https-redirect Enabled
    --link-to-default-domain "${link_to_default_domain}"
    --enabled-state Enabled
  )

  if [[ ${#custom_domains[@]} -gt 0 ]]; then
    base_args+=(--custom-domains)
    base_args+=("${custom_domains[@]}")
  fi

  if az afd route show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --endpoint-name "${AFD_ENDPOINT_NAME}" --route-name "${route_name}" >/dev/null 2>&1; then
    az afd route update "${base_args[@]}" --no-wait --output none
    return
  fi

  az afd route create "${base_args[@]}" --no-wait --output none
}

delete_route_if_exists() {
  local route_name="$1"
  if az afd route show \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --profile-name "${AFD_PROFILE_NAME}" \
    --endpoint-name "${AFD_ENDPOINT_NAME}" \
    --route-name "${route_name}" >/dev/null 2>&1; then
    az afd route delete \
      --resource-group "${AZ_RESOURCE_GROUP}" \
      --profile-name "${AFD_PROFILE_NAME}" \
      --endpoint-name "${AFD_ENDPOINT_NAME}" \
      --route-name "${route_name}" \
      --yes \
      --output none
  fi
}

upsert_waf_policy() {
  if az network front-door waf-policy show --resource-group "${AZ_RESOURCE_GROUP}" --name "${WAF_POLICY_NAME}" >/dev/null 2>&1; then
    return
  fi

  az network front-door waf-policy create \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --name "${WAF_POLICY_NAME}" \
    --location "${AZ_LOCATION}" \
    --mode Prevention \
    --sku Standard_AzureFrontDoor \
    --output none
}

upsert_security_policy() {
  local endpoint_id
  endpoint_id="$(az afd endpoint show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --endpoint-name "${AFD_ENDPOINT_NAME}" --query id -o tsv)"

  local domain_ids=("${endpoint_id}")
  while IFS= read -r item; do
    [[ -z "${item}" ]] && continue
    domain_ids+=("${item}")
  done < <(az afd custom-domain list --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --query "[].id" -o tsv)

  local waf_policy_id
  waf_policy_id="$(az network front-door waf-policy show --resource-group "${AZ_RESOURCE_GROUP}" --name "${WAF_POLICY_NAME}" --query id -o tsv)"

  if az afd security-policy show --resource-group "${AZ_RESOURCE_GROUP}" --profile-name "${AFD_PROFILE_NAME}" --security-policy-name "${SECURITY_POLICY_NAME}" >/dev/null 2>&1; then
    az afd security-policy update \
      --resource-group "${AZ_RESOURCE_GROUP}" \
      --profile-name "${AFD_PROFILE_NAME}" \
      --security-policy-name "${SECURITY_POLICY_NAME}" \
      --waf-policy "${waf_policy_id}" \
      --domains "${domain_ids[@]}" \
      --output none
    return
  fi

  az afd security-policy create \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --profile-name "${AFD_PROFILE_NAME}" \
    --security-policy-name "${SECURITY_POLICY_NAME}" \
    --waf-policy "${waf_policy_id}" \
    --domains "${domain_ids[@]}" \
    --output none
}

echo "[afd] resolving app origin hostnames"
SWA_HOST="$(az staticwebapp show --resource-group "${AZ_RESOURCE_GROUP}" --name "${SWA_NAME}" --query defaultHostname -o tsv)"
API_HOST="$(az containerapp show --resource-group "${AZ_RESOURCE_GROUP}" --name "${ORCHESTRATOR_APP_NAME}" --query properties.configuration.ingress.fqdn -o tsv)"
CHATKIT_HOST="$(az containerapp show --resource-group "${AZ_RESOURCE_GROUP}" --name "${CHATKIT_APP_NAME}" --query properties.configuration.ingress.fqdn -o tsv)"
APIM_GATEWAY_URL=""
APIM_GATEWAY_HOST=""
if is_true "${API_USE_APIM_GATEWAY}"; then
  APIM_GATEWAY_URL="$(az apim show --resource-group "${AZ_RESOURCE_GROUP}" --name "${APIM_NAME}" --query gatewayUrl -o tsv)"
  APIM_GATEWAY_HOST="${APIM_GATEWAY_URL#https://}"
  APIM_GATEWAY_HOST="${APIM_GATEWAY_HOST#http://}"
  APIM_GATEWAY_HOST="${APIM_GATEWAY_HOST%%/*}"
fi

upsert_profile
upsert_endpoint

upsert_origin_group og-ui '/'
upsert_origin_group og-api '/health'
upsert_origin_group og-chatkit '/health'
if is_true "${API_USE_APIM_GATEWAY}"; then
  upsert_origin_group og-apim '/health'
fi

upsert_origin og-ui origin-ui "${SWA_HOST}"
upsert_origin og-api origin-api "${API_HOST}"
upsert_origin og-chatkit origin-chatkit "${CHATKIT_HOST}"
if is_true "${API_USE_APIM_GATEWAY}"; then
  upsert_origin og-apim origin-apim "${APIM_GATEWAY_HOST}"
fi

# Default endpoint domain always serves UI.
upsert_route route-default-ui og-ui Enabled '/*'

if [[ -n "${WORKCORE_DOMAIN}" ]]; then
  echo "[afd] ensuring custom UI domain ${WORKCORE_DOMAIN}"
  upsert_custom_domain cd-workcore "${WORKCORE_DOMAIN}"
  wait_custom_domain_ready cd-workcore
  upsert_route route-workcore-custom og-ui Disabled '/*' cd-workcore
fi

if [[ -n "${CHATKIT_DOMAIN}" ]]; then
  echo "[afd] ensuring custom ChatKit domain ${CHATKIT_DOMAIN}"
  upsert_custom_domain cd-chatkit "${CHATKIT_DOMAIN}"
  wait_custom_domain_ready cd-chatkit
  upsert_route route-chatkit-custom og-chatkit Disabled '/*' cd-chatkit
fi

if [[ -n "${API_PRIMARY_DOMAIN}" ]]; then
  echo "[afd] ensuring primary API domain ${API_PRIMARY_DOMAIN}"
  upsert_custom_domain cd-api-primary "${API_PRIMARY_DOMAIN}"
  wait_custom_domain_ready cd-api-primary
  if is_true "${API_USE_APIM_GATEWAY}"; then
    delete_route_if_exists route-api-primary-chat
    upsert_route route-api-primary og-apim Disabled '/*' cd-api-primary
  else
    upsert_route route-api-primary-chat og-chatkit Disabled '/chat,/chat/*' cd-api-primary
    upsert_route route-api-primary og-api Disabled "${API_ROUTE_PATTERNS}" cd-api-primary
  fi
fi

if is_true "${ENABLE_SECONDARY_API_DOMAIN}"; then
  if [[ -z "${API_SECONDARY_DOMAIN}" ]]; then
    echo "ENABLE_SECONDARY_API_DOMAIN=true but API_SECONDARY_DOMAIN is empty" >&2
    exit 1
  fi
  echo "[afd] ensuring secondary API domain ${API_SECONDARY_DOMAIN}"
  upsert_custom_domain cd-api-secondary "${API_SECONDARY_DOMAIN}"
  wait_custom_domain_ready cd-api-secondary
  if is_true "${API_USE_APIM_GATEWAY}"; then
    delete_route_if_exists route-api-secondary-chat
    upsert_route route-api-secondary og-apim Disabled '/*' cd-api-secondary
  else
    upsert_route route-api-secondary-chat og-chatkit Disabled '/chat,/chat/*' cd-api-secondary
    upsert_route route-api-secondary og-api Disabled "${API_ROUTE_PATTERNS}" cd-api-secondary
  fi
else
  echo "[afd] secondary API domain is disabled (set ENABLE_SECONDARY_API_DOMAIN=true to enable)"
fi

if upsert_waf_policy; then
  upsert_security_policy
else
  echo "[afd] warning: unable to provision WAF policy; security policy attachment skipped"
fi

echo "[afd] deployment complete"
