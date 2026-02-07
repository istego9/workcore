#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/.env.docker"
COMPOSE_FILE="${ROOT}/docker-compose.workcore.yml"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${ROOT}/.env.docker.example" "${ENV_FILE}"
  echo "Created ${ENV_FILE} from .env.docker.example"
fi

if [[ -x "${ROOT}/scripts/docker_hosts.sh" ]]; then
  "${ROOT}/scripts/docker_hosts.sh" || true
else
  bash "${ROOT}/scripts/docker_hosts.sh" || true
fi

if [[ -x "${ROOT}/scripts/docker_certs.sh" ]]; then
  "${ROOT}/scripts/docker_certs.sh"
else
  bash "${ROOT}/scripts/docker_certs.sh"
fi

set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

WORKCORE_HTTP_PORT="${WORKCORE_HTTP_PORT:-80}"
WORKCORE_HTTPS_PORT="${WORKCORE_HTTPS_PORT:-443}"
PUBLIC_BUILDER_HOST="${PUBLIC_BUILDER_HOST:-workcore.build}"
PUBLIC_API_HOST="${PUBLIC_API_HOST:-api.workcore.build}"
PUBLIC_CHATKIT_HOST="${PUBLIC_CHATKIT_HOST:-chatkit.workcore.build}"

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build orchestrator builder
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d

echo ""
echo "WorkCore Docker stack is up."
if ! grep -Eq "(^|[[:space:]])${PUBLIC_BUILDER_HOST}([[:space:]]|$)" /etc/hosts \
  || ! grep -Eq "(^|[[:space:]])${PUBLIC_API_HOST}([[:space:]]|$)" /etc/hosts \
  || ! grep -Eq "(^|[[:space:]])${PUBLIC_CHATKIT_HOST}([[:space:]]|$)" /etc/hosts; then
  echo "Missing host mapping in /etc/hosts:"
  echo "  127.0.0.1 ${PUBLIC_BUILDER_HOST} ${PUBLIC_API_HOST} ${PUBLIC_CHATKIT_HOST}"
  echo "Run once in interactive terminal:"
  echo "  ./scripts/docker_trust.sh"
  echo ""
fi

http_prefix="http://${PUBLIC_BUILDER_HOST}"
https_prefix="https://${PUBLIC_BUILDER_HOST}"
api_http_prefix="http://${PUBLIC_API_HOST}"
api_https_prefix="https://${PUBLIC_API_HOST}"
chatkit_http_prefix="http://${PUBLIC_CHATKIT_HOST}"
chatkit_https_prefix="https://${PUBLIC_CHATKIT_HOST}"

if [[ "${WORKCORE_HTTP_PORT}" != "80" ]]; then
  http_prefix="${http_prefix}:${WORKCORE_HTTP_PORT}"
  api_http_prefix="${api_http_prefix}:${WORKCORE_HTTP_PORT}"
  chatkit_http_prefix="${chatkit_http_prefix}:${WORKCORE_HTTP_PORT}"
fi

if [[ "${WORKCORE_HTTPS_PORT}" != "443" ]]; then
  https_prefix="${https_prefix}:${WORKCORE_HTTPS_PORT}"
  api_https_prefix="${api_https_prefix}:${WORKCORE_HTTPS_PORT}"
  chatkit_https_prefix="${chatkit_https_prefix}:${WORKCORE_HTTPS_PORT}"
fi

echo "Main URLs:"
echo "  ${http_prefix}"
echo "  ${https_prefix}"
echo "  ${api_http_prefix}/health"
echo "  ${api_https_prefix}/health"
echo "  ${chatkit_http_prefix}/health"
echo "  ${chatkit_https_prefix}/health"
