#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v colima >/dev/null 2>&1; then
  echo "error: colima command not found" >&2
  exit 1
fi

status_output="$(colima status 2>&1 || true)"
if ! grep -q "colima is running" <<<"${status_output}"; then
  echo "error: colima is not running. Start it first: colima start" >&2
  exit 1
fi

echo "[1/4] Stopping docker/containerd and unmounting /dev/vdb1 mounts..."
colima ssh -- sh -lc '
  set -eu
  sudo systemctl stop docker.service docker.socket containerd.service || true
  sudo systemctl stop docker || true
  sudo umount /var/lib/docker 2>/dev/null || true
  sudo umount /var/lib/containerd 2>/dev/null || true
  sudo umount /var/lib/rancher 2>/dev/null || true
  sudo umount /var/lib/cni 2>/dev/null || true
  sudo umount /mnt/lima-colima 2>/dev/null || true
'

echo "[2/4] Running e2fsck on /dev/vdb1..."
set +e
colima ssh -- sh -lc 'sudo e2fsck -f -y /dev/vdb1'
fsck_status=$?
set -e
if [[ "${fsck_status}" -ne 0 && "${fsck_status}" -ne 1 && "${fsck_status}" -ne 2 ]]; then
  echo "error: e2fsck failed with exit code ${fsck_status}" >&2
  exit "${fsck_status}"
fi

echo "[3/4] Restarting Colima VM..."
colima stop
colima start

echo "[4/4] Verifying ext4 metadata health..."
"${ROOT}/scripts/colima_storage_check.sh"
echo "repair completed"
