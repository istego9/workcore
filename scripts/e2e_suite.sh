#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/.env.docker"
COMPOSE_FILE="${ROOT}/docker-compose.workcore.yml"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${ROOT}/.env.docker.example" "${ENV_FILE}"
fi

set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

E2E_BASE_URL="${E2E_BASE_URL:-http://workcore.build}"
E2E_API_BASE_URL="${E2E_API_BASE_URL:-http://api.workcore.build}"
E2E_CHATKIT_API_URL="${E2E_CHATKIT_API_URL:-http://chatkit.workcore.build/chatkit}"
E2E_API_AUTH_TOKEN="${E2E_API_AUTH_TOKEN:-${WORKCORE_API_AUTH_TOKEN:-}}"

echo "[e2e] backend run mode"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" exec -T orchestrator python scripts/e2e_test_mode.py

echo "[e2e] chatkit flow"
seed_out="$(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" exec -T orchestrator python scripts/seed_workflow.py)"
workflow_id="$(printf '%s\n' "${seed_out}" | awk -F= '/^workflow_id=/{print $2}')"
workflow_version_id="$(printf '%s\n' "${seed_out}" | awk -F= '/^version_id=/{print $2}')"

if [[ -z "${workflow_id}" || -z "${workflow_version_id}" ]]; then
  echo "failed to parse workflow bootstrap output" >&2
  exit 1
fi

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" exec -T \
  -e CHATKIT_BASE_URL=http://chatkit:8001 \
  -e CHATKIT_AUTH_TOKEN="${CHATKIT_AUTH_TOKEN:-dev_chatkit_token}" \
  -e CHATKIT_WORKFLOW_ID="${workflow_id}" \
  -e CHATKIT_WORKFLOW_VERSION_ID="${workflow_version_id}" \
  orchestrator python scripts/chatkit_e2e.py

echo "[e2e] builder playwright"
(
  cd "${ROOT}/apps/builder"
  E2E_BASE_URL="${E2E_BASE_URL}" \
  E2E_API_BASE_URL="${E2E_API_BASE_URL}" \
  E2E_CHATKIT_API_URL="${E2E_CHATKIT_API_URL}" \
  E2E_API_AUTH_TOKEN="${E2E_API_AUTH_TOKEN}" \
  npm run test:e2e
)

echo "[e2e] all suites passed"
