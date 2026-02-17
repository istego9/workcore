#!/usr/bin/env bash
set -euo pipefail

UID_VALUE="$(id -u)"
LAUNCHD_DST_DIR="${HOME}/Library/LaunchAgents"
AUTOSTART_DIR="${HOME}/Library/Application Support/workcore/autostart"

STACK_LABEL="com.workcore.stack"
CLOUDFLARED_LABEL="com.workcore.cloudflared"

STACK_DST="${LAUNCHD_DST_DIR}/com.workcore.stack.plist"
CLOUDFLARED_DST="${LAUNCHD_DST_DIR}/com.workcore.cloudflared.plist"

launchctl bootout "gui/${UID_VALUE}/${STACK_LABEL}" >/dev/null 2>&1 || true
launchctl bootout "gui/${UID_VALUE}/${CLOUDFLARED_LABEL}" >/dev/null 2>&1 || true

rm -f "${STACK_DST}" "${CLOUDFLARED_DST}"
rm -f \
  "${AUTOSTART_DIR}/workcore_autostart_boot.sh" \
  "${AUTOSTART_DIR}/workcore_autostart_cloudflared.sh"

echo "Uninstalled LaunchAgents:"
echo "  - ${STACK_LABEL}"
echo "  - ${CLOUDFLARED_LABEL}"
