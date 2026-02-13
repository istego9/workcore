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

cleanup_workflow_ids=()

delete_workflow() {
  local workflow_id="$1"
  local url="${E2E_API_BASE_URL%/}/workflows/${workflow_id}"
  local response_file http_code
  response_file="$(mktemp)"

  if [[ -n "${E2E_API_AUTH_TOKEN}" ]]; then
    http_code="$(curl -sS -o "${response_file}" -w "%{http_code}" -X DELETE \
      -H "Authorization: Bearer ${E2E_API_AUTH_TOKEN}" \
      -H "Content-Type: application/json" \
      "${url}")" || http_code="000"
  else
    http_code="$(curl -sS -o "${response_file}" -w "%{http_code}" -X DELETE \
      -H "Content-Type: application/json" \
      "${url}")" || http_code="000"
  fi

  if [[ "${http_code}" != "200" && "${http_code}" != "204" && "${http_code}" != "404" ]]; then
    echo "[e2e][cleanup] failed deleting ${workflow_id}: HTTP ${http_code} $(cat "${response_file}")" >&2
    rm -f "${response_file}"
    return 1
  fi

  rm -f "${response_file}"
  echo "[e2e][cleanup] deleted ${workflow_id}"
  return 0
}

cleanup_on_exit() {
  local exit_code="$?"
  local cleanup_failed=0
  local workflow_id

  for workflow_id in "${cleanup_workflow_ids[@]}"; do
    [[ -z "${workflow_id}" ]] && continue
    if ! delete_workflow "${workflow_id}"; then
      cleanup_failed=1
    fi
  done

  if [[ "${exit_code}" -eq 0 && "${cleanup_failed}" -ne 0 ]]; then
    exit_code=1
  fi

  trap - EXIT
  exit "${exit_code}"
}

trap cleanup_on_exit EXIT

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
cleanup_workflow_ids+=("${workflow_id}")

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
