#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -x "${ROOT}/scripts/colima_storage_check.sh" ]]; then
  "${ROOT}/scripts/colima_storage_check.sh"
else
  bash "${ROOT}/scripts/colima_storage_check.sh"
fi

explicit_orch_url="${ORCH_URL:-}"
explicit_builder_url="${BUILDER_URL:-}"

if [[ "${USE_PROXY:-}" == "1" ]]; then
  PROXY_PORT="${PROXY_PORT:-${WORKCORE_HTTP_PORT:-8080}}"
  BUILDER_HOST="${BUILDER_HOST:-builder.localhost}"
  API_HOST="${API_HOST:-api.localhost}"
  ORCH_BASE="http://${API_HOST}"
  BUILDER_BASE="http://${BUILDER_HOST}"
  if [[ "${PROXY_PORT}" != "80" ]]; then
    ORCH_BASE="${ORCH_BASE}:${PROXY_PORT}"
    BUILDER_BASE="${BUILDER_BASE}:${PROXY_PORT}"
  fi
  ORCH_URL="${ORCH_URL:-${ORCH_BASE}/health}"
  BUILDER_URL="${BUILDER_URL:-${BUILDER_BASE}/}"
else
  ORCH_PORT="${ORCH_PORT:-8000}"
  BUILDER_PORT="${BUILDER_PORT:-5183}"
  ORCH_URL="${ORCH_URL:-http://127.0.0.1:${ORCH_PORT}/health}"
  BUILDER_URL="${BUILDER_URL:-http://127.0.0.1:${BUILDER_PORT}/}"
fi

check_url() {
  local url="$1"
  curl -fsS "${url}" >/dev/null 2>&1
}

if ! check_url "${ORCH_URL}" || ! check_url "${BUILDER_URL}"; then
  if [[ "${USE_PROXY:-}" != "1" && -z "${explicit_orch_url}" && -z "${explicit_builder_url}" ]]; then
    PROXY_PORT="${WORKCORE_HTTP_PORT:-80}"
    PROXY_ORCH_URL="http://api.workcore.build/health"
    PROXY_BUILDER_URL="http://workcore.build/"
    if [[ "${PROXY_PORT}" != "80" ]]; then
      PROXY_ORCH_URL="http://api.workcore.build:${PROXY_PORT}/health"
      PROXY_BUILDER_URL="http://workcore.build:${PROXY_PORT}/"
    fi
    if check_url "${PROXY_ORCH_URL}" && check_url "${PROXY_BUILDER_URL}"; then
      ORCH_URL="${PROXY_ORCH_URL}"
      BUILDER_URL="${PROXY_BUILDER_URL}"
    else
      echo "health check failed for local and proxy URLs" >&2
      echo "local orchestrator: ${ORCH_URL}" >&2
      echo "local builder: ${BUILDER_URL}" >&2
      echo "proxy orchestrator: ${PROXY_ORCH_URL}" >&2
      echo "proxy builder: ${PROXY_BUILDER_URL}" >&2
      exit 1
    fi
  else
    echo "health check failed" >&2
    echo "orchestrator: ${ORCH_URL}" >&2
    echo "builder: ${BUILDER_URL}" >&2
    exit 1
  fi
fi

(cd apps/builder && npm run test:unit)

if [[ "${RUN_E2E:-0}" == "1" ]]; then
  ./scripts/e2e_suite.sh
fi

echo "ok: orchestrator+builder health + builder tests"
