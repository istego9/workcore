#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -t 0 ]]; then
  echo "Run this script in an interactive terminal."
  exit 1
fi

"${ROOT}/scripts/docker_hosts.sh"

if command -v mkcert >/dev/null 2>&1; then
  echo "Installing mkcert local CA into trust store..."
  mkcert -install
else
  echo "mkcert is not installed; HTTPS will use self-signed certs."
fi

echo "Local DNS + TLS trust setup complete."
