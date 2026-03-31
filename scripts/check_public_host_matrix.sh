#!/usr/bin/env bash
set -euo pipefail

PRIMARY_HOST="${API_PRIMARY_DOMAIN:-api.hq21.tech}"
SECONDARY_HOST="${API_SECONDARY_DOMAIN:-api.runwcr.com}"
ENABLE_SECONDARY="${ENABLE_SECONDARY_API_DOMAIN:-true}"
PUBLIC_API_HOSTS="${PUBLIC_API_HOSTS:-}"

normalize_flag() {
  printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]'
}

build_hosts() {
  if [[ -n "${PUBLIC_API_HOSTS}" ]]; then
    echo "${PUBLIC_API_HOSTS}" | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed '/^$/d'
    return
  fi
  printf '%s\n' "${PRIMARY_HOST}"
  normalized_secondary="$(normalize_flag "${ENABLE_SECONDARY}")"
  if [[ "${normalized_secondary}" == "1" || "${normalized_secondary}" == "true" || "${normalized_secondary}" == "yes" || "${normalized_secondary}" == "on" ]]; then
    printf '%s\n' "${SECONDARY_HOST}"
  fi
}

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

first_signature=""
first_host=""

while IFS= read -r host; do
  [[ -z "${host}" ]] && continue
  openapi_url="https://${host}/openapi.yaml"
  caps_url="https://${host}/integration-capabilities"
  openapi_file="${TMP_DIR}/${host}-openapi.yaml"

  echo "[host-matrix] checking ${host}"
  curl -fsS "${openapi_url}" > "${openapi_file}"
  grep -q '^  /integration-capabilities:' "${openapi_file}" || {
    echo "[host-matrix] ${host}: OpenAPI is missing /integration-capabilities" >&2
    exit 1
  }
  curl -fsS "${caps_url}" > "${TMP_DIR}/${host}.json"

  signature="$(
    python3 - <<'PY' "${TMP_DIR}/${host}.json"
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
widget_extensions = payload.get("widget_extensions") or {}
if isinstance(widget_extensions, dict):
    rich_chart = widget_extensions.get("RichChart")
    if isinstance(rich_chart, dict):
        schema_url = rich_chart.get("schema_url")
        if isinstance(schema_url, str) and schema_url.strip():
            rich_chart = dict(rich_chart)
            rich_chart["schema_url"] = urlparse(schema_url).path or schema_url
            widget_extensions = dict(widget_extensions)
            widget_extensions["RichChart"] = rich_chart
signature = {
    "chat": payload.get("chat"),
    "widget_extensions": widget_extensions,
}
print(json.dumps(signature, sort_keys=True))
PY
  )"

  if [[ -z "${first_signature}" ]]; then
    first_signature="${signature}"
    first_host="${host}"
    continue
  fi

  if [[ "${signature}" != "${first_signature}" ]]; then
    echo "[host-matrix] compatibility mismatch: ${host} differs from ${first_host}" >&2
    echo "[host-matrix] ${first_host}: ${first_signature}" >&2
    echo "[host-matrix] ${host}: ${signature}" >&2
    exit 1
  fi
done < <(build_hosts)

echo "[host-matrix] public host compatibility matrix passed"
