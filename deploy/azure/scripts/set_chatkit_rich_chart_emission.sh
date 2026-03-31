#!/usr/bin/env bash
set -euo pipefail

AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-}"
CHATKIT_APP_NAME="${CHATKIT_APP_NAME:-}"
ENABLE_RICH_CHART_EMISSION="${ENABLE_RICH_CHART_EMISSION:-1}"

if [[ -z "${AZ_RESOURCE_GROUP}" ]]; then
  echo "AZ_RESOURCE_GROUP is required" >&2
  exit 1
fi

if [[ -z "${CHATKIT_APP_NAME}" ]]; then
  echo "CHATKIT_APP_NAME is required" >&2
  exit 1
fi

normalize_flag() {
  local value="${1:-}"
  case "$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on)
      echo "1"
      ;;
    *)
      echo "0"
      ;;
  esac
}

normalized_flag="$(normalize_flag "${ENABLE_RICH_CHART_EMISSION}")"

az containerapp update \
  --resource-group "${AZ_RESOURCE_GROUP}" \
  --name "${CHATKIT_APP_NAME}" \
  --set-env-vars WORKCORE_CHATKIT_ENABLE_RICH_CHART_EMISSION="${normalized_flag}" \
  --output none

echo "RichChart emission flag set to ${normalized_flag} on ${CHATKIT_APP_NAME}"
