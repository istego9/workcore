#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/.env.docker"
COMPOSE_FILE="${ROOT}/docker-compose.workcore.yml"

if [[ -f "${ENV_FILE}" ]]; then
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" down --remove-orphans
else
  docker compose -f "${COMPOSE_FILE}" down --remove-orphans
fi
