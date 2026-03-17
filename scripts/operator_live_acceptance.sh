#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACTS_DIR="${ROOT}/artifacts/acceptance/operator-live"

mkdir -p "${ARTIFACTS_DIR}"

echo "[operator-live] builder playwright live operator suite"
(
  cd "${ROOT}/apps/builder"
  E2E_OPERATOR_ARTIFACTS_DIR="${ARTIFACTS_DIR}" \
  npm run test:e2e:operator-live
)

echo "[operator-live] artifacts directory: ${ARTIFACTS_DIR}"
