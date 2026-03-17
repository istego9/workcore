#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

AZ_RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-rg-workcore-prod-uaen}"
SWA_NAME="${SWA_NAME:-swa-workcore-prod-uaen}"
BUILDER_DIR="${BUILDER_DIR:-${ROOT_DIR}/apps/builder}"
BUILD_OUTPUT_DIR="${BUILD_OUTPUT_DIR:-${BUILDER_DIR}/dist}"
SWA_DEPLOYMENT_TOKEN="${SWA_DEPLOYMENT_TOKEN:-}"
SKIP_NPM_CI="${SKIP_NPM_CI:-false}"
SKIP_BUILD="${SKIP_BUILD:-false}"
SWA_ALLOW_INSECURE_TLS_DOWNLOAD="${SWA_ALLOW_INSECURE_TLS_DOWNLOAD:-false}"
SWA_CLI_VERBOSE="${SWA_CLI_VERBOSE:-log}"

is_true() {
  local value
  value="$(echo "${1:-}" | tr '[:upper:]' '[:lower:]')"
  [[ "${value}" == "1" || "${value}" == "true" || "${value}" == "yes" || "${value}" == "on" ]]
}

if [[ ! -d "${BUILDER_DIR}" ]]; then
  echo "Builder directory not found: ${BUILDER_DIR}" >&2
  exit 1
fi

if [[ -z "${SWA_DEPLOYMENT_TOKEN}" ]]; then
  SWA_DEPLOYMENT_TOKEN="$(
    az staticwebapp secrets list \
      --resource-group "${AZ_RESOURCE_GROUP}" \
      --name "${SWA_NAME}" \
      --query properties.apiKey \
      -o tsv
  )"
fi

if [[ -z "${SWA_DEPLOYMENT_TOKEN}" ]]; then
  echo "SWA deployment token is empty for ${SWA_NAME}" >&2
  exit 1
fi

pushd "${BUILDER_DIR}" >/dev/null
if ! is_true "${SKIP_NPM_CI}"; then
  npm ci
fi
if ! is_true "${SKIP_BUILD}"; then
  npm run build
fi
popd >/dev/null

if [[ ! -f "${BUILD_OUTPUT_DIR}/index.html" ]]; then
  echo "Missing build artifact: ${BUILD_OUTPUT_DIR}/index.html" >&2
  exit 1
fi

if [[ ! -f "${BUILD_OUTPUT_DIR}/staticwebapp.config.json" ]]; then
  echo "Missing SWA auth config: ${BUILD_OUTPUT_DIR}/staticwebapp.config.json" >&2
  exit 1
fi

echo "[swa] deploying builder artifact to ${SWA_NAME}"
if is_true "${SWA_ALLOW_INSECURE_TLS_DOWNLOAD}"; then
  echo "[swa] warning: NODE_TLS_REJECT_UNAUTHORIZED=0 is enabled for SWA CLI download path"
  NODE_TLS_REJECT_UNAUTHORIZED=0 npm_config_ignore_scripts=true npx --yes @azure/static-web-apps-cli@2.0.7 deploy "${BUILD_OUTPUT_DIR}" \
    --deployment-token "${SWA_DEPLOYMENT_TOKEN}" \
    --env production \
    --verbose "${SWA_CLI_VERBOSE}"
else
  npm_config_ignore_scripts=true npx --yes @azure/static-web-apps-cli@2.0.7 deploy "${BUILD_OUTPUT_DIR}" \
    --deployment-token "${SWA_DEPLOYMENT_TOKEN}" \
    --env production \
    --verbose "${SWA_CLI_VERBOSE}"
fi

echo "[swa] deployment complete"
