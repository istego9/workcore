#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export PROXY_PORT="${PROXY_PORT:-8080}"
export BUILDER_PORT="${BUILDER_PORT:-5183}"
export ORCH_PORT="${ORCH_PORT:-8000}"
export CHATKIT_PORT="${CHATKIT_PORT:-8001}"

exec caddy run --config "${ROOT}/Caddyfile" --adapter caddyfile
