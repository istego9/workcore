#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/acceptance_package.sh --task-id <id> [options]

Options:
  --task-id <id>       Required. Artifact folder name (letters, numbers, ., _, -).
  --url <url>          Page URL for acceptance screenshot test.
                       Default: ${E2E_BASE_URL:-http://workcore.build}/?e2e=1
  --wait-ms <ms>       Delay before screenshot capture. Default: 3000
  --selector <css>     Optional CSS selector to wait for before capture.
  --full-page          Capture full-page screenshots.
  --no-zip             Skip ZIP creation.
  -h, --help           Show this help.
EOF
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TASK_ID=""
TARGET_URL="${E2E_BASE_URL:-http://workcore.build}/?e2e=1"
WAIT_MS=3000
WAIT_SELECTOR=""
FULL_PAGE=0
CREATE_ZIP=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task-id)
      TASK_ID="${2:-}"
      shift 2
      ;;
    --url)
      TARGET_URL="${2:-}"
      shift 2
      ;;
    --wait-ms)
      WAIT_MS="${2:-}"
      shift 2
      ;;
    --selector)
      WAIT_SELECTOR="${2:-}"
      shift 2
      ;;
    --full-page)
      FULL_PAGE=1
      shift 1
      ;;
    --no-zip)
      CREATE_ZIP=0
      shift 1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${TASK_ID}" ]]; then
  echo "--task-id is required." >&2
  usage
  exit 1
fi

if ! [[ "${TASK_ID}" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "--task-id contains unsupported characters: ${TASK_ID}" >&2
  exit 1
fi

if ! [[ "${WAIT_MS}" =~ ^[0-9]+$ ]]; then
  echo "--wait-ms must be a positive integer." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required but not found in PATH." >&2
  exit 1
fi

BUILD_DIR="${ROOT}/apps/builder"
ACCEPTANCE_ROOT="${ROOT}/artifacts/acceptance"
PACKAGE_DIR="${ACCEPTANCE_ROOT}/${TASK_ID}"
SCREENSHOTS_DIR="${PACKAGE_DIR}/screenshots"
REPORT_PATH="${PACKAGE_DIR}/ACCEPTANCE.md"
ZIP_PATH="${ACCEPTANCE_ROOT}/${TASK_ID}.zip"
CAPTURED_AT_UTC="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"

mkdir -p "${SCREENSHOTS_DIR}"

(
  cd "${BUILD_DIR}"
  ACCEPTANCE_SCREENSHOTS_DIR="${SCREENSHOTS_DIR}" \
  ACCEPTANCE_URL="${TARGET_URL}" \
  ACCEPTANCE_WAIT_MS="${WAIT_MS}" \
  ACCEPTANCE_SELECTOR="${WAIT_SELECTOR}" \
  ACCEPTANCE_FULL_PAGE="${FULL_PAGE}" \
  npm run test:e2e:acceptance
)

if [[ ! -f "${REPORT_PATH}" ]]; then
  cat > "${REPORT_PATH}" <<EOF
# Acceptance Package

## Goal/Scope
- TODO

## Changes
- TODO

## Diff Summary
- TODO

## Checks Executed
- TODO

## Screenshots
- \`screenshots/desktop.png\` (captured ${CAPTURED_AT_UTC})
- \`screenshots/mobile.png\` (captured ${CAPTURED_AT_UTC})

## Risks/TODO
- TODO

## Verdict
- PENDING
EOF
fi

if [[ "${CREATE_ZIP}" -eq 1 ]]; then
  (
    cd "${ACCEPTANCE_ROOT}"
    find "${TASK_ID}" -name '.DS_Store' -delete
    zip -r -FS "${TASK_ID}.zip" "${TASK_ID}" -x '*.DS_Store' >/dev/null
  )
fi

echo "Acceptance package prepared:"
echo "  Task ID: ${TASK_ID}"
echo "  URL: ${TARGET_URL}"
echo "  Desktop screenshot: ${SCREENSHOTS_DIR}/desktop.png"
echo "  Mobile screenshot: ${SCREENSHOTS_DIR}/mobile.png"
echo "  Report: ${REPORT_PATH}"
if [[ "${CREATE_ZIP}" -eq 1 ]]; then
  echo "  ZIP: ${ZIP_PATH}"
fi
