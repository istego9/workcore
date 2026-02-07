#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/.env.docker"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${ROOT}/.env.docker.example" "${ENV_FILE}"
fi

set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

PUBLIC_BUILDER_HOST="${PUBLIC_BUILDER_HOST:-workcore.build}"
PUBLIC_API_HOST="${PUBLIC_API_HOST:-api.workcore.build}"
PUBLIC_CHATKIT_HOST="${PUBLIC_CHATKIT_HOST:-chatkit.workcore.build}"
HOSTS=("${PUBLIC_BUILDER_HOST}" "${PUBLIC_API_HOST}" "${PUBLIC_CHATKIT_HOST}")

missing_hosts=()
for host in "${HOSTS[@]}"; do
  if ! grep -Eq "(^|[[:space:]])${host}([[:space:]]|$)" /etc/hosts; then
    missing_hosts+=("${host}")
  fi
done

if [[ ${#missing_hosts[@]} -eq 0 ]]; then
  echo "Local DNS entries already exist in /etc/hosts."
  exit 0
fi

hosts_line="127.0.0.1 ${missing_hosts[*]}"

if [[ -t 0 ]]; then
  echo "Adding missing local DNS entries to /etc/hosts:"
  echo "  ${hosts_line}"
  if echo "${hosts_line}" | sudo tee -a /etc/hosts >/dev/null; then
    sudo dscacheutil -flushcache >/dev/null 2>&1 || true
    sudo killall -HUP mDNSResponder >/dev/null 2>&1 || true
    echo "Updated /etc/hosts and flushed DNS cache."
    exit 0
  fi
fi

echo "Missing local DNS entries:"
echo "  ${hosts_line}"
echo "Run once in an interactive terminal:"
echo "  echo '${hosts_line}' | sudo tee -a /etc/hosts"
echo "  sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder"
