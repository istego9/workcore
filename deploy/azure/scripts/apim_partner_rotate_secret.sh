#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PARTNERS_CONFIG_PATH="${PARTNERS_CONFIG_PATH:-${ROOT_DIR}/deploy/azure/config/partners.yaml}"

OVERLAP_DAYS="${OVERLAP_DAYS:-14}"
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
secret_expiry_months = int(match.get("secret_expiry_months", 12))
status = str(match.get("status", "active")).strip().lower() or "active"

print("\t".join([partner_id, entra_display_name, entra_app_id, str(secret_expiry_months), status]))
PY
}

IFS=$'\t' read -r PARTNER_ID_VALUE ENTRA_APP_DISPLAY_NAME ENTRA_APP_ID SECRET_EXPIRY_MONTHS STATUS <<< "$(read_partner_record)"

if [[ "${STATUS}" != "active" ]]; then
  echo "partner '${PARTNER_ID_VALUE}' is not active in config (status=${STATUS}); rotation skipped" >&2
  exit 1
fi

if [[ -z "${ENTRA_APP_ID}" ]]; then
  ENTRA_APP_ID="$(az ad app list --display-name "${ENTRA_APP_DISPLAY_NAME}" --query "[0].appId" -o tsv)"
fi

if [[ -z "${ENTRA_APP_ID}" ]]; then
  echo "could not resolve Entra app id for ${PARTNER_ID_VALUE}" >&2
  exit 1
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
  --display-name "workcore-rotate-${PARTNER_ID_VALUE}-$(date -u +%Y%m%d)" \
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
  echo "failed to rotate partner secret for ${PARTNER_ID_VALUE}" >&2
  exit 1
fi

cat <<EOF
[partner-rotate] completed
partner_id: ${PARTNER_ID_VALUE}
client_id: ${ENTRA_APP_ID}
new_secret_expires_at: ${SECRET_END_DATE}
recommended_overlap_days: ${OVERLAP_DAYS}

Deliver this new client_secret via secure channel:
${CLIENT_SECRET}
EOF
