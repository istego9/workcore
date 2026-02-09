#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Coexist mode: keep HQ21 on 80/443 and move WorkCore proxy to non-conflicting ports.
export WORKCORE_HTTP_PORT="${WORKCORE_HTTP_PORT:-8080}"
export WORKCORE_HTTPS_PORT="${WORKCORE_HTTPS_PORT:-8443}"

echo "Starting WorkCore in coexist mode with HQ21."
echo "Using WORKCORE_HTTP_PORT=${WORKCORE_HTTP_PORT}, WORKCORE_HTTPS_PORT=${WORKCORE_HTTPS_PORT}."

if [[ -x "${ROOT}/scripts/docker_up.sh" ]]; then
  "${ROOT}/scripts/docker_up.sh"
else
  bash "${ROOT}/scripts/docker_up.sh"
fi
