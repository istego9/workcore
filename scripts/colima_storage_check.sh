#!/usr/bin/env bash
set -euo pipefail

if [[ "${SKIP_COLIMA_STORAGE_CHECK:-0}" == "1" ]]; then
  echo "skip: colima storage check disabled (SKIP_COLIMA_STORAGE_CHECK=1)"
  exit 0
fi

if ! command -v colima >/dev/null 2>&1; then
  echo "info: colima not installed; skipping colima storage check"
  exit 0
fi

status_output="$(colima status 2>&1 || true)"
if ! grep -q "colima is running" <<<"${status_output}"; then
  echo "info: colima is not running; skipping colima storage check"
  exit 0
fi

fs_meta="$(colima ssh -- sh -lc 'sudo tune2fs -l /dev/vdb1 2>/dev/null | egrep "Filesystem state:|FS Error count:"' || true)"
if [[ -z "${fs_meta}" ]]; then
  echo "warning: unable to inspect /dev/vdb1 ext4 metadata; skipping strict storage gate"
  exit 0
fi

fs_state="$(awk -F: '/Filesystem state/{gsub(/^ +| +$/, "", $2); print tolower($2)}' <<<"${fs_meta}" | head -n 1)"
fs_errors="$(awk -F: '/FS Error count/{gsub(/^ +| +$/, "", $2); print $2}' <<<"${fs_meta}" | head -n 1)"
if [[ -z "${fs_errors}" ]]; then
  fs_errors="0"
fi

if [[ "${fs_state}" != "clean" || "${fs_errors}" != "0" ]]; then
  echo "error: colima data disk /dev/vdb1 reports ext4 issues (state='${fs_state}', fs_error_count='${fs_errors}')"
  echo "error: this can trigger Postgres I/O failures (e.g. pg_filenode.map read errors)"
  echo "error: run ./scripts/colima_repair_vdb1.sh before starting/retrying the stack"
  exit 1
fi

echo "ok: colima /dev/vdb1 ext4 metadata is clean"
