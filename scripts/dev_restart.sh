#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${ROOT}/.env"
  set +a
fi

PROXY_PORT="${PROXY_PORT:-8080}"
BUILDER_PORT="${BUILDER_PORT:-5183}"
ORCH_PORT="${ORCH_PORT:-8000}"
CHATKIT_PORT="${CHATKIT_PORT:-8001}"

"${ROOT}/.venv/bin/python" "${ROOT}/scripts/migrate.py"

for port in "${ORCH_PORT}" "${CHATKIT_PORT}" "${BUILDER_PORT}" "${PROXY_PORT}"; do
  if lsof -ti "tcp:${port}" >/dev/null 2>&1; then
    lsof -ti "tcp:${port}" | while read -r pid; do
      kill "${pid}"
    done
  fi
done

mkdir -p "${ROOT}/logs"

nohup "${ROOT}/.venv/bin/uvicorn" apps.orchestrator.api.service:app \
  --host 0.0.0.0 --port "${ORCH_PORT}" \
  > "${ROOT}/logs/orchestrator.log" 2>&1 &

(cd "${ROOT}/apps/builder" && \
  nohup env VITE_DEV_PORT="${BUILDER_PORT}" VITE_API_BASE_URL="http://api.localhost:${PROXY_PORT}" \
  npm run dev > "${ROOT}/logs/builder.log" 2>&1 &)

nohup "${ROOT}/scripts/dev_proxy.sh" > "${ROOT}/logs/proxy.log" 2>&1 &

"${ROOT}/scripts/chatkit_up.sh"

for i in {1..60}; do
  healthy=1
  curl -fsS "http://127.0.0.1:${ORCH_PORT}/health" >/dev/null 2>&1 || healthy=0
  curl -fsS "http://127.0.0.1:${CHATKIT_PORT}/health" >/dev/null 2>&1 || healthy=0
  curl -fsS "http://127.0.0.1:${BUILDER_PORT}/" >/dev/null 2>&1 || healthy=0
  curl -fsS "http://127.0.0.1:${PROXY_PORT}/" -H "Host: builder.localhost" >/dev/null 2>&1 || healthy=0

  if [[ "${healthy}" == "1" ]]; then
    break
  fi
  if [[ "$i" == "60" ]]; then
    echo "dev services health check failed" >&2
    exit 1
  fi
  sleep 1
done

echo "dev services restarted (db-backed) on ports: api=${ORCH_PORT}, builder=${BUILDER_PORT}, proxy=${PROXY_PORT}, chatkit=${CHATKIT_PORT}"
