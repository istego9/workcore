#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export PROXY_PORT="${PROXY_PORT:-8080}"
export BUILDER_PORT="${BUILDER_PORT:-5183}"
export ORCH_PORT="${ORCH_PORT:-8000}"
export CHATKIT_PORT="${CHATKIT_PORT:-8001}"

# Backward compatibility: allow legacy *_UPSTREAM=host:port env overrides.
if [[ -n "${BUILDER_UPSTREAM:-}" && "${BUILDER_UPSTREAM}" == *:* ]]; then
  export BUILDER_UPSTREAM_HOST="${BUILDER_UPSTREAM%:*}"
  export BUILDER_PORT="${BUILDER_UPSTREAM##*:}"
fi
if [[ -n "${API_UPSTREAM:-}" && "${API_UPSTREAM}" == *:* ]]; then
  export API_UPSTREAM_HOST="${API_UPSTREAM%:*}"
  export ORCH_PORT="${API_UPSTREAM##*:}"
fi
if [[ -n "${CHATKIT_UPSTREAM:-}" && "${CHATKIT_UPSTREAM}" == *:* ]]; then
  export CHATKIT_UPSTREAM_HOST="${CHATKIT_UPSTREAM%:*}"
  export CHATKIT_PORT="${CHATKIT_UPSTREAM##*:}"
fi

export BUILDER_UPSTREAM_HOST="${BUILDER_UPSTREAM_HOST:-127.0.0.1}"
export API_UPSTREAM_HOST="${API_UPSTREAM_HOST:-127.0.0.1}"
export CHATKIT_UPSTREAM_HOST="${CHATKIT_UPSTREAM_HOST:-127.0.0.1}"

# Keep legacy env names populated for older tooling.
export BUILDER_UPSTREAM="${BUILDER_UPSTREAM:-${BUILDER_UPSTREAM_HOST}:${BUILDER_PORT}}"
export API_UPSTREAM="${API_UPSTREAM:-${API_UPSTREAM_HOST}:${ORCH_PORT}}"
export CHATKIT_UPSTREAM="${CHATKIT_UPSTREAM:-${CHATKIT_UPSTREAM_HOST}:${CHATKIT_PORT}}"

exec caddy run --config "${ROOT}/Caddyfile" --adapter caddyfile
