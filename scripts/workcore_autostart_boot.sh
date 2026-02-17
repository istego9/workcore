#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

CONTAINERS=(
  "workcore-local-postgres-1"
  "workcore-local-minio-1"
  "workcore-local-orchestrator-1"
  "workcore-local-chatkit-1"
  "workcore-local-builder-1"
  "workcore-local-proxy-1"
)
WAIT_SECONDS="${WORKCORE_AUTOSTART_DOCKER_WAIT_SECONDS:-900}"
SLEEP_SECONDS=5

log() {
  echo "[workcore-autostart] $*"
}

override_containers_if_set() {
  local raw
  raw="${WORKCORE_AUTOSTART_CONTAINERS:-}"
  if [[ -z "${raw}" ]]; then
    return
  fi
  IFS=' ' read -r -a CONTAINERS <<< "${raw}"
}

docker_ready() {
  docker info >/dev/null 2>&1
}

containers_running() {
  local name state
  for name in "${CONTAINERS[@]}"; do
    if ! docker container inspect "${name}" >/dev/null 2>&1; then
      return 1
    fi
    state="$(docker inspect -f '{{.State.Running}}' "${name}")"
    if [[ "${state}" != "true" ]]; then
      return 1
    fi
  done
  return 0
}

start_existing_containers() {
  local name
  for name in "${CONTAINERS[@]}"; do
    if docker container inspect "${name}" >/dev/null 2>&1; then
      docker start "${name}" >/dev/null 2>&1 || true
    fi
  done
}

wait_for_docker() {
  local attempts max_attempts
  max_attempts=$((WAIT_SECONDS / SLEEP_SECONDS))
  attempts=0
  until docker_ready; do
    attempts=$((attempts + 1))
    if (( attempts >= max_attempts )); then
      log "Docker did not become ready within ${WAIT_SECONDS}s."
      return 1
    fi
    sleep "${SLEEP_SECONDS}"
  done
}

main() {
  override_containers_if_set

  if ! command -v docker >/dev/null 2>&1; then
    log "docker binary not found in PATH."
    exit 1
  fi

  if ! wait_for_docker; then
    exit 1
  fi

  if containers_running; then
    log "WorkCore stack is already running."
    exit 0
  fi

  log "Starting existing WorkCore containers."
  start_existing_containers

  if ! containers_running; then
    log "Some containers are missing or still stopped. Run ./scripts/docker_up.sh once manually."
    exit 1
  fi

  local probe_port
  probe_port="${WORKCORE_HTTP_PORT:-80}"
  if ! curl -fsS -H "Host: ${WORKCORE_API_HOST_HEADER:-api.workcore.build}" "http://127.0.0.1:${probe_port}/health" >/dev/null 2>&1; then
    log "Warning: post-start API health probe failed on 127.0.0.1:${probe_port}."
  else
    log "API health probe is OK."
  fi
}

main "$@"
