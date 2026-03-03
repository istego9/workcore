#!/usr/bin/env sh
set -eu
exec uvicorn apps.orchestrator.chatkit.service:app --host 0.0.0.0 --port 8001
