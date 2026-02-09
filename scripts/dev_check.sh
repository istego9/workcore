#!/usr/bin/env bash
set -euo pipefail

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

curl -fsS "${ORCH_URL}" >/dev/null
curl -fsS "${BUILDER_URL}" >/dev/null

(cd apps/builder && npm run test:unit)

if [[ "${RUN_E2E:-0}" == "1" ]]; then
  ./scripts/e2e_suite.sh
fi

echo "ok: orchestrator+builder health + builder tests"
