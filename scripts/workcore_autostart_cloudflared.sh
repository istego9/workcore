#!/usr/bin/env bash
set -euo pipefail

CLOUDFLARED_BIN="${CLOUDFLARED_BIN:-/opt/homebrew/bin/cloudflared}"
CONFIG_FILE="${WORKCORE_CLOUDFLARED_CONFIG:-${HOME}/.cloudflared/config.yml}"

log() {
  echo "[workcore-cloudflared] $*"
}

if [[ ! -x "${CLOUDFLARED_BIN}" ]]; then
  log "cloudflared binary not found at ${CLOUDFLARED_BIN}."
  exit 1
fi

if [[ ! -f "${CONFIG_FILE}" ]]; then
  log "Config file not found: ${CONFIG_FILE}"
  exit 1
fi

"${CLOUDFLARED_BIN}" tunnel --config "${CONFIG_FILE}" ingress validate
exec "${CLOUDFLARED_BIN}" tunnel --config "${CONFIG_FILE}" run
