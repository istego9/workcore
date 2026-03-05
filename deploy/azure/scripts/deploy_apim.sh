#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PARTNERS_CONFIG_PATH="${PARTNERS_CONFIG_PATH:-${ROOT_DIR}/deploy/azure/config/partners.yaml}"
OPENAPI_SPEC_PATH="${OPENAPI_SPEC_PATH:-${ROOT_DIR}/docs/api/openapi.yaml}"

AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-rg-workcore-prod-uaen}"
APIM_NAME="${APIM_NAME:-apim-workcore-prod-uaen}"
KEY_VAULT_NAME="${KEY_VAULT_NAME:-kv-workcore-prod-uaen}"
ORCHESTRATOR_APP_NAME="${ORCHESTRATOR_APP_NAME:-ca-orchestrator}"
CHATKIT_APP_NAME="${CHATKIT_APP_NAME:-ca-chatkit}"

APIM_API_ID="${APIM_API_ID:-workcore}"
APIM_API_DISPLAY_NAME="${APIM_API_DISPLAY_NAME:-WorkCore Public API}"
APIM_API_PATH="${APIM_API_PATH:-}"
APIM_OAUTH_AUDIENCE="${APIM_OAUTH_AUDIENCE:-api://workcore-partner-api}"
APIM_ENFORCE_PARTNER_MAP="${APIM_ENFORCE_PARTNER_MAP:-true}"

ENTRA_TENANT_ID="${ENTRA_TENANT_ID:-${AZURE_TENANT_ID:-}}"
if [[ -z "${ENTRA_TENANT_ID}" ]]; then
  ENTRA_TENANT_ID="$(az account show --query tenantId -o tsv)"
fi

OPENID_CONFIG_URL="https://login.microsoftonline.com/${ENTRA_TENANT_ID}/v2.0/.well-known/openid-configuration"

is_true() {
  local value
  value="$(echo "${1:-}" | tr '[:upper:]' '[:lower:]')"
  [[ "${value}" == "1" || "${value}" == "true" || "${value}" == "yes" || "${value}" == "on" ]]
}

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

upsert_named_value() {
  local named_value_id="$1"
  local value="$2"
  local secret="${3:-false}"
  local display_name="${4:-$1}"
  if az apim nv show \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --service-name "${APIM_NAME}" \
    --named-value-id "${named_value_id}" >/dev/null 2>&1; then
    az apim nv update \
      --resource-group "${AZ_RESOURCE_GROUP}" \
      --service-name "${APIM_NAME}" \
      --named-value-id "${named_value_id}" \
      --value "${value}" \
      --secret "${secret}" \
      --output none
    return
  fi
  az apim nv create \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --service-name "${APIM_NAME}" \
    --named-value-id "${named_value_id}" \
    --display-name "${display_name}" \
    --value "${value}" \
    --secret "${secret}" \
    --output none
}

build_partner_map_json() {
  python3 - <<'PY' "${PARTNERS_CONFIG_PATH}"
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
if not path.exists():
    print("{}")
    raise SystemExit(0)

raw = path.read_text(encoding="utf-8").strip()
if not raw:
    print("{}")
    raise SystemExit(0)

try:
    data = json.loads(raw)
except Exception as exc:
    raise SystemExit(f"partners config must be valid JSON/YAML 1.2 JSON subset: {exc}")

partners = data.get("partners") if isinstance(data, dict) else None
if not isinstance(partners, list):
    print("{}")
    raise SystemExit(0)

result = {}
for partner in partners:
    if not isinstance(partner, dict):
        continue
    app_id = str(partner.get("entra_app_id") or "").strip()
    status = str(partner.get("status") or "active").strip().lower()
    if not app_id or status != "active":
        continue
    tenant_id = str(partner.get("tenant_id_pinned") or "").strip()
    if not tenant_id:
        continue
    partner_id = str(partner.get("partner_id") or app_id).strip()
    rate_limit_profile = str(partner.get("rate_limit_profile") or "default").strip()
    allowed_domains = partner.get("allowed_domains")
    if not isinstance(allowed_domains, list):
        allowed_domains = []
    result[app_id] = {
        "partner_id": partner_id,
        "tenant_id": tenant_id,
        "status": status,
        "rate_limit_profile": rate_limit_profile,
        "allowed_domains": [str(item).strip() for item in allowed_domains if str(item).strip()],
    }

print(json.dumps(result, separators=(",", ":"), sort_keys=True))
PY
}

merge_partner_map_json() {
  python3 - <<'PY' "$1" "$2"
import json
import sys

raw_existing, raw_from_config = sys.argv[1:]
try:
    existing = json.loads(raw_existing) if raw_existing.strip() else {}
except Exception:
    existing = {}
if not isinstance(existing, dict):
    existing = {}

try:
    from_config = json.loads(raw_from_config) if raw_from_config.strip() else {}
except Exception:
    from_config = {}
if not isinstance(from_config, dict):
    from_config = {}

# Keep current APIM partner map when config has no active entries.
if not from_config:
    print(json.dumps(existing, separators=(",", ":"), sort_keys=True))
    raise SystemExit(0)

merged = dict(existing)
merged.update(from_config)
print(json.dumps(merged, separators=(",", ":"), sort_keys=True))
PY
}

echo "[apim] validating required resources"
az apim show --resource-group "${AZ_RESOURCE_GROUP}" --name "${APIM_NAME}" --query name -o tsv >/dev/null
ORCHESTRATOR_HOST="$(az containerapp show --resource-group "${AZ_RESOURCE_GROUP}" --name "${ORCHESTRATOR_APP_NAME}" --query properties.configuration.ingress.fqdn -o tsv)"
CHATKIT_HOST="$(az containerapp show --resource-group "${AZ_RESOURCE_GROUP}" --name "${CHATKIT_APP_NAME}" --query properties.configuration.ingress.fqdn -o tsv)"

if [[ -z "${ORCHESTRATOR_HOST}" || -z "${CHATKIT_HOST}" ]]; then
  echo "orchestrator/chatkit ingress FQDN could not be resolved" >&2
  exit 1
fi

WORKCORE_API_AUTH_TOKEN="${WORKCORE_API_AUTH_TOKEN:-$(get_secret_or_default workcore-api-auth-token)}"
CHATKIT_AUTH_TOKEN="${CHATKIT_AUTH_TOKEN:-$(get_secret_or_default chatkit-auth-token)}"

if [[ -z "${WORKCORE_API_AUTH_TOKEN}" || -z "${CHATKIT_AUTH_TOKEN}" ]]; then
  echo "workcore-api-auth-token and chatkit-auth-token must be available in Key Vault or env" >&2
  exit 1
fi

if [[ ! -f "${OPENAPI_SPEC_PATH}" ]]; then
  echo "OpenAPI spec not found: ${OPENAPI_SPEC_PATH}" >&2
  exit 1
fi

echo "[apim] importing API contract (${APIM_API_ID})"
api_import_args=(
  --resource-group "${AZ_RESOURCE_GROUP}"
  --service-name "${APIM_NAME}"
  --api-id "${APIM_API_ID}"
  --display-name "${APIM_API_DISPLAY_NAME}"
  --specification-format OpenApi
  --specification-path "${OPENAPI_SPEC_PATH}"
  --service-url "https://${ORCHESTRATOR_HOST}"
  --subscription-required false
  --protocols https
)
if [[ -n "${APIM_API_PATH}" ]]; then
  api_import_args+=(--path "${APIM_API_PATH}")
else
  api_import_args+=(--path "")
fi
az apim api import "${api_import_args[@]}" --output none

echo "[apim] syncing named values"
PARTNER_MAP_FROM_CONFIG_JSON="$(build_partner_map_json)"
CURRENT_PARTNER_MAP_JSON="$(az apim nv show \
  --resource-group "${AZ_RESOURCE_GROUP}" \
  --service-name "${APIM_NAME}" \
  --named-value-id partner-app-map \
  --query value -o tsv 2>/dev/null || true)"
PARTNER_MAP_JSON="$(merge_partner_map_json "${CURRENT_PARTNER_MAP_JSON}" "${PARTNER_MAP_FROM_CONFIG_JSON}")"
upsert_named_value "backend-orchestrator-url" "https://${ORCHESTRATOR_HOST}" false "backend-orchestrator-url"
upsert_named_value "backend-chatkit-url" "https://${CHATKIT_HOST}" false "backend-chatkit-url"
upsert_named_value "backend-orchestrator-token" "${WORKCORE_API_AUTH_TOKEN}" true "backend-orchestrator-token"
upsert_named_value "backend-chatkit-token" "${CHATKIT_AUTH_TOKEN}" true "backend-chatkit-token"
upsert_named_value "partner-app-map" "${PARTNER_MAP_JSON}" false "partner-app-map"
upsert_named_value "oauth-openid-config-url" "${OPENID_CONFIG_URL}" false "oauth-openid-config-url"
upsert_named_value "oauth-audience" "${APIM_OAUTH_AUDIENCE}" false "oauth-audience"
upsert_named_value "enforce-partner-map" "${APIM_ENFORCE_PARTNER_MAP}" false "enforce-partner-map"

echo "[apim] applying API policy"
POLICY_FILE="$(mktemp)"
trap 'rm -f "${POLICY_FILE}"' EXIT
cat > "${POLICY_FILE}" <<'EOF_POLICY'
<policies>
  <inbound>
    <base />
    <set-variable name="requestPath" value='@((context.Request.OriginalUrl?.Path ?? context.Request.Url.Path).ToLowerInvariant())' />
    <set-variable name="isPublicRoute" value='@{
      var path = (string)context.Variables["requestPath"];
      return path == "/health"
        || path == "/openapi.yaml"
        || path == "/api-reference"
        || path == "/workflow-authoring-guide"
        || path == "/agent-integration-kit"
        || path == "/agent-integration-kit.json"
        || path == "/agent-integration-test"
        || path == "/agent-integration-test.json"
        || path == "/agent-integration-test/validate-draft"
        || path.StartsWith("/schemas/")
        || path.StartsWith("/webhooks/inbound/");
    }' />
    <set-variable name="isChatRoute" value='@{
      var path = (string)context.Variables["requestPath"];
      return path == "/chat" || path.StartsWith("/chat/");
    }' />
    <set-variable name="clientAppId" value="" />
    <choose>
      <when condition='@(!(bool)context.Variables["isPublicRoute"])'>
        <validate-jwt
          header-name="Authorization"
          require-scheme="Bearer"
          failed-validation-httpcode="401"
          failed-validation-error-message="missing or invalid oauth token">
          <openid-config url="{{oauth-openid-config-url}}" />
          <audiences>
            <audience>{{oauth-audience}}</audience>
          </audiences>
        </validate-jwt>
        <set-variable name="clientAppId" value='@{
          var authHeader = context.Request.Headers.GetValueOrDefault("Authorization", "");
          var jwt = authHeader.AsJwt();
          if (jwt == null) { return ""; }
          var appId = jwt.Claims.GetValueOrDefault("appid");
          if (!string.IsNullOrWhiteSpace(appId)) { return appId; }
          return jwt.Claims.GetValueOrDefault("azp") ?? "";
        }' />
        <set-variable name="partnerMapRaw" value="{{partner-app-map}}" />
        <set-variable name="partnerMap" value='@{
          var raw = (string)context.Variables["partnerMapRaw"];
          if (string.IsNullOrWhiteSpace(raw)) { return new Newtonsoft.Json.Linq.JObject(); }
          return Newtonsoft.Json.Linq.JObject.Parse(raw);
        }' />
        <choose>
          <when condition='@{
            var enforce = "{{enforce-partner-map}}".ToLowerInvariant();
            if (!(enforce == "1" || enforce == "true" || enforce == "yes" || enforce == "on")) { return false; }
            var appId = (string)context.Variables["clientAppId"];
            var map = (Newtonsoft.Json.Linq.JObject)context.Variables["partnerMap"];
            return string.IsNullOrWhiteSpace(appId) || map[appId] == null;
          }'>
            <return-response>
              <set-status code="401" reason="Unauthorized" />
              <set-header name="Content-Type" exists-action="override">
                <value>application/json</value>
              </set-header>
              <set-body>{"error":{"code":"UNAUTHORIZED","message":"unknown partner application"}}</set-body>
            </return-response>
          </when>
        </choose>
        <set-header name="X-Tenant-Id" exists-action="override">
          <value>@{
            var appId = (string)context.Variables["clientAppId"];
            var map = (Newtonsoft.Json.Linq.JObject)context.Variables["partnerMap"];
            var tenantId = (string)map[appId]?["tenant_id"];
            return string.IsNullOrWhiteSpace(tenantId) ? "local" : tenantId;
          }</value>
        </set-header>
        <set-header name="X-Partner-Id" exists-action="override">
          <value>@{
            var appId = (string)context.Variables["clientAppId"];
            var map = (Newtonsoft.Json.Linq.JObject)context.Variables["partnerMap"];
            var partnerId = (string)map[appId]?["partner_id"];
            return string.IsNullOrWhiteSpace(partnerId) ? appId : partnerId;
          }</value>
        </set-header>
      </when>
    </choose>
    <set-header name="X-Correlation-Id" exists-action="skip">
      <value>@($"corr_{Guid.NewGuid().ToString("N").Substring(0, 12)}")</value>
    </set-header>
    <set-header name="X-Trace-Id" exists-action="skip">
      <value>@($"trace_{Guid.NewGuid().ToString("N").Substring(0, 12)}")</value>
    </set-header>
    <choose>
      <when condition='@((bool)context.Variables["isChatRoute"])'>
        <choose>
          <when condition='@{
            var path = (string)context.Variables["requestPath"];
            return path == "/chat";
          }'>
            <rewrite-uri template="/chatkit" copy-unmatched-params="true" />
          </when>
          <when condition='@{
            var path = (string)context.Variables["requestPath"];
            return path.StartsWith("/chat/");
          }'>
            <rewrite-uri template='@{
              var path = (string)context.Variables["requestPath"];
              return "/chatkit" + path.Substring(5);
            }' copy-unmatched-params="true" />
          </when>
        </choose>
        <set-backend-service base-url="{{backend-chatkit-url}}" />
        <set-header name="Authorization" exists-action="override">
          <value>Bearer {{backend-chatkit-token}}</value>
        </set-header>
      </when>
      <otherwise>
        <set-backend-service base-url="{{backend-orchestrator-url}}" />
        <set-header name="Authorization" exists-action="override">
          <value>Bearer {{backend-orchestrator-token}}</value>
        </set-header>
      </otherwise>
    </choose>
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>
EOF_POLICY

if az apim api policy -h >/dev/null 2>&1; then
  if az apim api policy show \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --service-name "${APIM_NAME}" \
    --api-id "${APIM_API_ID}" >/dev/null 2>&1; then
    az apim api policy update \
      --resource-group "${AZ_RESOURCE_GROUP}" \
      --service-name "${APIM_NAME}" \
      --api-id "${APIM_API_ID}" \
      --xml-content @"${POLICY_FILE}" \
      --output none
  else
    az apim api policy create \
      --resource-group "${AZ_RESOURCE_GROUP}" \
      --service-name "${APIM_NAME}" \
      --api-id "${APIM_API_ID}" \
      --xml-content @"${POLICY_FILE}" \
      --output none
  fi
else
  SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
  POLICY_PAYLOAD_FILE="$(mktemp)"
  python3 - <<'PY' "${POLICY_FILE}" "${POLICY_PAYLOAD_FILE}"
import json
import pathlib
import sys

policy_path = pathlib.Path(sys.argv[1])
payload_path = pathlib.Path(sys.argv[2])
value = policy_path.read_text(encoding="utf-8")
payload_path.write_text(
    json.dumps(
        {
            "properties": {
                "format": "rawxml",
                "value": value,
            }
        },
        ensure_ascii=True,
    ),
    encoding="utf-8",
)
PY
  az rest \
    --method put \
    --uri "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${AZ_RESOURCE_GROUP}/providers/Microsoft.ApiManagement/service/${APIM_NAME}/apis/${APIM_API_ID}/policies/policy?api-version=2023-05-01-preview" \
    --body @"${POLICY_PAYLOAD_FILE}" \
    --headers "Content-Type=application/json" \
    --output none
  rm -f "${POLICY_PAYLOAD_FILE}"
fi

echo "[apim] deployment complete"
