#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PARTNERS_CONFIG_PATH="${PARTNERS_CONFIG_PATH:-${ROOT_DIR}/deploy/azure/config/partners.yaml}"

AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-rg-workcore-prod-uaen}"
APIM_NAME="${APIM_NAME:-apim-workcore-prod-uaen}"
APIM_OAUTH_AUDIENCE="${APIM_OAUTH_AUDIENCE:-api://workcore-partner-api}"
ENTRA_TENANT_ID="${ENTRA_TENANT_ID:-${AZURE_TENANT_ID:-}}"

PARTNER_ID="${PARTNER_ID:-${1:-}}"
if [[ -z "${PARTNER_ID}" ]]; then
  echo "Usage: PARTNER_ID=<partner_id> $0" >&2
  exit 1
fi

if [[ -z "${ENTRA_TENANT_ID}" ]]; then
  ENTRA_TENANT_ID="$(az account show --query tenantId -o tsv)"
fi

if [[ ! -f "${PARTNERS_CONFIG_PATH}" ]]; then
  echo "partners config not found: ${PARTNERS_CONFIG_PATH}" >&2
  exit 1
fi

read_partner_record() {
  python3 - <<'PY' "${PARTNERS_CONFIG_PATH}" "${PARTNER_ID}"
import json
import pathlib
import sys

config_path = pathlib.Path(sys.argv[1])
partner_id = sys.argv[2]
raw = config_path.read_text(encoding="utf-8").strip()
data = json.loads(raw) if raw else {}
partners = data.get("partners", []) if isinstance(data, dict) else []

match = None
for item in partners:
    if isinstance(item, dict) and str(item.get("partner_id", "")).strip() == partner_id:
        match = item
        break

if match is None:
    raise SystemExit(f"partner_id '{partner_id}' was not found in {config_path}")

tenant_id = str(match.get("tenant_id_pinned", "")).strip()
if not tenant_id:
    raise SystemExit("tenant_id_pinned is required in partners config")

display_name = str(match.get("display_name", partner_id)).strip() or partner_id
entra_display_name = str(match.get("entra_app_display_name", f"workcore-{partner_id}")).strip() or f"workcore-{partner_id}"
status = str(match.get("status", "active")).strip().lower() or "active"
rate_limit_profile = str(match.get("rate_limit_profile", "default")).strip() or "default"
secret_expiry_months = int(match.get("secret_expiry_months", 12))
allowed_domains = match.get("allowed_domains")
if not isinstance(allowed_domains, list):
    allowed_domains = []
entra_app_id = str(match.get("entra_app_id", "")).strip()

print(
    "\t".join(
        [
            partner_id,
            display_name,
            entra_display_name,
            tenant_id,
            status,
            rate_limit_profile,
            str(secret_expiry_months),
            json.dumps(allowed_domains, separators=(",", ":"), ensure_ascii=True),
            entra_app_id,
        ]
    )
)
PY
}

IFS=$'\t' read -r PARTNER_ID_VALUE DISPLAY_NAME ENTRA_APP_DISPLAY_NAME TENANT_ID_PINNED STATUS RATE_LIMIT_PROFILE SECRET_EXPIRY_MONTHS ALLOWED_DOMAINS_JSON ENTRA_APP_ID <<< "$(read_partner_record)"

if [[ "${STATUS}" != "active" ]]; then
  echo "partner '${PARTNER_ID_VALUE}' is not active in config (status=${STATUS}); onboarding skipped" >&2
  exit 1
fi

if [[ -z "${ENTRA_APP_ID}" ]]; then
  ENTRA_APP_ID="$(az ad app list --display-name "${ENTRA_APP_DISPLAY_NAME}" --query "[0].appId" -o tsv)"
fi

if [[ -z "${ENTRA_APP_ID}" ]]; then
  echo "[partner-onboard] creating Entra app registration ${ENTRA_APP_DISPLAY_NAME}"
  ENTRA_APP_ID="$(az ad app create --display-name "${ENTRA_APP_DISPLAY_NAME}" --sign-in-audience AzureADMyOrg --query appId -o tsv)"
else
  echo "[partner-onboard] using existing Entra app registration ${ENTRA_APP_ID}"
fi

SP_OBJECT_ID="$(az ad sp show --id "${ENTRA_APP_ID}" --query id -o tsv 2>/dev/null || true)"
if [[ -z "${SP_OBJECT_ID}" ]]; then
  echo "[partner-onboard] creating service principal for ${ENTRA_APP_ID}"
  az ad sp create --id "${ENTRA_APP_ID}" --output none
  SP_OBJECT_ID="$(az ad sp show --id "${ENTRA_APP_ID}" --query id -o tsv)"
fi

SECRET_END_DATE="$(python3 - <<'PY' "${SECRET_EXPIRY_MONTHS}"
from datetime import datetime
import calendar
import sys

months = max(1, int(sys.argv[1]))
now = datetime.utcnow()
year = now.year + ((now.month - 1 + months) // 12)
month = ((now.month - 1 + months) % 12) + 1
day = min(now.day, calendar.monthrange(year, month)[1])
target = now.replace(year=year, month=month, day=day)
print(target.strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
)"

SECRET_PAYLOAD="$(az ad app credential reset \
  --id "${ENTRA_APP_ID}" \
  --append \
  --display-name "workcore-${PARTNER_ID_VALUE}-$(date -u +%Y%m%d)" \
  --end-date "${SECRET_END_DATE}" \
  --query "{client_id:appId,client_secret:password}" \
  -o json)"

CLIENT_SECRET="$(python3 - <<'PY' "${SECRET_PAYLOAD}"
import json,sys
payload = json.loads(sys.argv[1])
print(payload.get("client_secret", ""))
PY
)"

if [[ -z "${CLIENT_SECRET}" ]]; then
  echo "failed to create partner client secret" >&2
  exit 1
fi

CURRENT_MAP_JSON="$(az apim nv show \
  --resource-group "${AZ_RESOURCE_GROUP}" \
  --service-name "${APIM_NAME}" \
  --named-value-id partner-app-map \
  --query value -o tsv 2>/dev/null || true)"
if [[ -z "${CURRENT_MAP_JSON}" ]]; then
  CURRENT_MAP_JSON="{}"
fi

UPDATED_MAP_JSON="$(python3 - <<'PY' "${CURRENT_MAP_JSON}" "${ENTRA_APP_ID}" "${PARTNER_ID_VALUE}" "${TENANT_ID_PINNED}" "${RATE_LIMIT_PROFILE}" "${ALLOWED_DOMAINS_JSON}"
import json
import sys

raw_map, app_id, partner_id, tenant_id, rate_profile, allowed_domains_raw = sys.argv[1:]
try:
    payload = json.loads(raw_map) if raw_map.strip() else {}
except Exception:
    payload = {}
if not isinstance(payload, dict):
    payload = {}
try:
    allowed_domains = json.loads(allowed_domains_raw) if allowed_domains_raw.strip() else []
except Exception:
    allowed_domains = []
if not isinstance(allowed_domains, list):
    allowed_domains = []

payload[app_id] = {
    "partner_id": partner_id,
    "tenant_id": tenant_id,
    "status": "active",
    "rate_limit_profile": rate_profile,
    "allowed_domains": [str(item).strip() for item in allowed_domains if str(item).strip()],
}

print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
PY
)"

if az apim nv show --resource-group "${AZ_RESOURCE_GROUP}" --service-name "${APIM_NAME}" --named-value-id partner-app-map >/dev/null 2>&1; then
  az apim nv update \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --service-name "${APIM_NAME}" \
    --named-value-id partner-app-map \
    --value "${UPDATED_MAP_JSON}" \
    --secret false \
    --output none
else
  az apim nv create \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --service-name "${APIM_NAME}" \
    --named-value-id partner-app-map \
    --display-name partner-app-map \
    --value "${UPDATED_MAP_JSON}" \
    --secret false \
    --output none
fi

TOKEN_SCOPE="${APIM_OAUTH_AUDIENCE}"
if [[ "${TOKEN_SCOPE}" != */.default ]]; then
  TOKEN_SCOPE="${TOKEN_SCOPE}/.default"
fi

cat <<EOF
[partner-onboard] completed
partner_id: ${PARTNER_ID_VALUE}
display_name: ${DISPLAY_NAME}
client_id: ${ENTRA_APP_ID}
client_secret_expires_at: ${SECRET_END_DATE}
token_endpoint: https://login.microsoftonline.com/${ENTRA_TENANT_ID}/oauth2/v2.0/token
scope: ${TOKEN_SCOPE}

Use this once-only client_secret value and deliver it via secure channel:
${CLIENT_SECRET}
EOF
