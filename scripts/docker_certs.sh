#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/.env.docker"
FORCE_REGENERATE=0

if [[ "${1:-}" == "--force" ]]; then
  FORCE_REGENERATE=1
fi

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
CERTS_DIR="${WORKCORE_CERTS_DIR:-${ROOT}/.certs}"
CERT_FILE="${WORKCORE_CERT_FILE:-${CERTS_DIR}/workcore.build.pem}"
KEY_FILE="${WORKCORE_CERT_KEY_FILE:-${CERTS_DIR}/workcore.build-key.pem}"

mkdir -p "${CERTS_DIR}"

DOMAINS=(
  "${PUBLIC_BUILDER_HOST}"
  "${PUBLIC_API_HOST}"
  "${PUBLIC_CHATKIT_HOST}"
  "localhost"
  "127.0.0.1"
)

is_ipv4() {
  [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]
}

cert_matches_domains() {
  local san_text host expected
  san_text="$(openssl x509 -in "${CERT_FILE}" -noout -ext subjectAltName 2>/dev/null || true)"
  for host in "${DOMAINS[@]}"; do
    if is_ipv4 "${host}"; then
      expected="IP Address:${host}"
    else
      expected="DNS:${host}"
    fi
    if [[ "${san_text}" != *"${expected}"* ]]; then
      return 1
    fi
  done
  return 0
}

cert_matches_key() {
  local cert_pub key_pub
  cert_pub="$(openssl x509 -in "${CERT_FILE}" -pubkey -noout 2>/dev/null | openssl pkey -pubin -outform pem 2>/dev/null || true)"
  key_pub="$(openssl pkey -in "${KEY_FILE}" -pubout -outform pem 2>/dev/null || true)"
  [[ -n "${cert_pub}" && "${cert_pub}" == "${key_pub}" ]]
}

cert_is_usable() {
  [[ -s "${CERT_FILE}" && -s "${KEY_FILE}" ]] || return 1
  openssl x509 -in "${CERT_FILE}" -noout >/dev/null 2>&1 || return 1
  openssl pkey -in "${KEY_FILE}" -noout >/dev/null 2>&1 || return 1
  openssl x509 -in "${CERT_FILE}" -noout -checkend 86400 >/dev/null 2>&1 || return 1
  cert_matches_domains || return 1
  cert_matches_key || return 1
  return 0
}

if [[ "${FORCE_REGENERATE}" -eq 0 ]]; then
  if cert_is_usable; then
    echo "TLS certificate is valid and reused:"
    echo "  ${CERT_FILE}"
    echo "  ${KEY_FILE}"
    exit 0
  fi
  if [[ -s "${CERT_FILE}" || -s "${KEY_FILE}" ]]; then
    echo "Existing TLS certificate/key are invalid or outdated; regenerating..."
  fi
fi

if command -v mkcert >/dev/null 2>&1; then
  if ! mkcert -install >/dev/null 2>&1; then
    echo "mkcert root CA is not installed in system trust store." >&2
    echo "Run this once in an interactive terminal:" >&2
    echo "  mkcert -install" >&2
  fi
  mkcert -cert-file "${CERT_FILE}" -key-file "${KEY_FILE}" "${DOMAINS[@]}"
  echo "Generated trusted local TLS certificate via mkcert:"
  echo "  ${CERT_FILE}"
  echo "  ${KEY_FILE}"
  exit 0
fi

echo "mkcert not found, generating self-signed cert with openssl (browser may show warning)." >&2
SAN_LIST="DNS:${PUBLIC_BUILDER_HOST},DNS:${PUBLIC_API_HOST},DNS:${PUBLIC_CHATKIT_HOST},DNS:localhost,IP:127.0.0.1"
openssl req \
  -x509 \
  -nodes \
  -newkey rsa:2048 \
  -sha256 \
  -days 825 \
  -keyout "${KEY_FILE}" \
  -out "${CERT_FILE}" \
  -subj "/CN=${PUBLIC_BUILDER_HOST}" \
  -addext "subjectAltName=${SAN_LIST}" >/dev/null 2>&1

echo "Generated self-signed TLS certificate:"
echo "  ${CERT_FILE}"
echo "  ${KEY_FILE}"
