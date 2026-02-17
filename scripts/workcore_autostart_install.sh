#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHD_SRC_DIR="${ROOT}/deploy/launchd"
LAUNCHD_DST_DIR="${HOME}/Library/LaunchAgents"
AUTOSTART_DIR="${HOME}/Library/Application Support/workcore/autostart"
LOG_DIR="${HOME}/Library/Logs/workcore"
UID_VALUE="$(id -u)"

STACK_LABEL="com.workcore.stack"
CLOUDFLARED_LABEL="com.workcore.cloudflared"

STACK_TEMPLATE="${LAUNCHD_SRC_DIR}/com.workcore.stack.plist"
CLOUDFLARED_TEMPLATE="${LAUNCHD_SRC_DIR}/com.workcore.cloudflared.plist"

STACK_DST="${LAUNCHD_DST_DIR}/com.workcore.stack.plist"
CLOUDFLARED_DST="${LAUNCHD_DST_DIR}/com.workcore.cloudflared.plist"

install_one() {
  local template="$1"
  local destination="$2"
  sed \
    -e "s#__WORKCORE_AUTOSTART_DIR__#${AUTOSTART_DIR}#g" \
    -e "s#__HOME__#${HOME}#g" \
    "${template}" > "${destination}"
}

reload_agent() {
  local label="$1"
  local plist="$2"
  local attempt
  launchctl bootout "gui/${UID_VALUE}/${label}" >/dev/null 2>&1 || true
  for attempt in {1..10}; do
    if launchctl bootstrap "gui/${UID_VALUE}" "${plist}" >/dev/null 2>&1; then
      break
    fi
    sleep 1
    launchctl bootout "gui/${UID_VALUE}/${label}" >/dev/null 2>&1 || true
    if [[ "${attempt}" -eq 10 ]]; then
      echo "Failed to bootstrap ${label} after retries." >&2
      launchctl bootstrap "gui/${UID_VALUE}" "${plist}"
    fi
  done
  launchctl enable "gui/${UID_VALUE}/${label}"
}

mkdir -p "${LAUNCHD_DST_DIR}" "${LOG_DIR}" "${AUTOSTART_DIR}"

install -m 755 \
  "${ROOT}/scripts/workcore_autostart_boot.sh" \
  "${AUTOSTART_DIR}/workcore_autostart_boot.sh"
install -m 755 \
  "${ROOT}/scripts/workcore_autostart_cloudflared.sh" \
  "${AUTOSTART_DIR}/workcore_autostart_cloudflared.sh"

install_one "${STACK_TEMPLATE}" "${STACK_DST}"
install_one "${CLOUDFLARED_TEMPLATE}" "${CLOUDFLARED_DST}"

reload_agent "${STACK_LABEL}" "${STACK_DST}"
reload_agent "${CLOUDFLARED_LABEL}" "${CLOUDFLARED_DST}"

echo "Installed and started LaunchAgents:"
echo "  - ${STACK_LABEL}"
echo "  - ${CLOUDFLARED_LABEL}"
echo ""
echo "Inspect status:"
echo "  launchctl print gui/${UID_VALUE}/${STACK_LABEL} | sed -n '1,40p'"
echo "  launchctl print gui/${UID_VALUE}/${CLOUDFLARED_LABEL} | sed -n '1,40p'"
