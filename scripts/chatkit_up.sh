#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${ROOT}/.env"
  set +a
fi

CHATKIT_PORT="${CHATKIT_PORT:-8001}"

brew services start minio >/dev/null 2>&1 || true

./.venv/bin/python scripts/migrate.py
./.venv/bin/python scripts/workflow_bootstrap.py --draft scripts/drafts/approval.json

pkill -f "uvicorn apps.orchestrator.chatkit.service:app" >/dev/null 2>&1 || true
mkdir -p logs
nohup .venv/bin/uvicorn apps.orchestrator.chatkit.service:app --port "${CHATKIT_PORT}" --log-level info > logs/chatkit.log 2>&1 &

for i in {1..45}; do
  if curl -fsS "http://127.0.0.1:${CHATKIT_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  if [[ "$i" == "45" ]]; then
    echo "chatkit health check failed on port ${CHATKIT_PORT}" >&2
    exit 1
  fi
  sleep 1
done

echo "ChatKit service started on http://127.0.0.1:${CHATKIT_PORT} (logs/chatkit.log)"
