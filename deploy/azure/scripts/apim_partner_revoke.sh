#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PARTNERS_CONFIG_PATH="${PARTNERS_CONFIG_PATH:-${ROOT_DIR}/deploy/azure/config/partners.yaml}"

AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-rg-workcore-prod-uaen}"
APIM_NAME="${APIM_NAME:-apim-workcore-prod-uaen}"

PARTNER_ID="${PARTNER_ID:-${1:-}}"
if [[ -z "${PARTNER_ID}" ]]; then
  echo "Usage: PARTNER_ID=<partner_id> $0" >&2
  exit 1
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

entra_app_id = str(match.get("entra_app_id", "")).strip()
entra_display_name = str(match.get("entra_app_display_name", f"workcore-{partner_id}")).strip() or f"workcore-{partner_id}"
print("\t".join([partner_id, entra_display_name, entra_app_id]))
PY
}

IFS=$'\t' read -r PARTNER_ID_VALUE ENTRA_APP_DISPLAY_NAME ENTRA_APP_ID <<< "$(read_partner_record)"

if [[ -z "${ENTRA_APP_ID}" ]]; then
  ENTRA_APP_ID="$(az ad app list --display-name "${ENTRA_APP_DISPLAY_NAME}" --query "[0].appId" -o tsv)"
fi

if [[ -z "${ENTRA_APP_ID}" ]]; then
  echo "could not resolve Entra app id for ${PARTNER_ID_VALUE}" >&2
  exit 1
fi

SP_OBJECT_ID="$(az ad sp show --id "${ENTRA_APP_ID}" --query id -o tsv 2>/dev/null || true)"
if [[ -n "${SP_OBJECT_ID}" ]]; then
  az ad sp update --id "${SP_OBJECT_ID}" --set accountEnabled=false --output none
fi

CURRENT_MAP_JSON="$(az apim nv show \
  --resource-group "${AZ_RESOURCE_GROUP}" \
  --service-name "${APIM_NAME}" \
  --named-value-id partner-app-map \
  --query value -o tsv 2>/dev/null || true)"

if [[ -z "${CURRENT_MAP_JSON}" ]]; then
  CURRENT_MAP_JSON="{}"
fi

UPDATED_MAP_JSON="$(python3 - <<'PY' "${CURRENT_MAP_JSON}" "${ENTRA_APP_ID}"
import json
import sys

raw_map = sys.argv[1]
app_id = sys.argv[2]
try:
    payload = json.loads(raw_map) if raw_map.strip() else {}
except Exception:
    payload = {}
if not isinstance(payload, dict):
    payload = {}
payload.pop(app_id, None)
print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
PY
)"

if az apim nv show --resource-group "${AZ_RESOURCE_GROUP}" --service-name "${APIM_NAME}" --named-value-id partner-app-map >/dev/null 2>&1; then
  az apim nv update \
    --resource-group "${AZ_RESOURCE_GROUP}" \
    --service-name "${APIM_NAME}" \
    --named-value-id partner-app-map \
    --display-name partner-app-map \
    --value "${UPDATED_MAP_JSON}" \
    --secret false \
    --output none
fi

cat <<EOF
[partner-revoke] completed
partner_id: ${PARTNER_ID_VALUE}
client_id: ${ENTRA_APP_ID}
service_principal_disabled: ${SP_OBJECT_ID:+true}
apim_mapping_removed: true
EOF
