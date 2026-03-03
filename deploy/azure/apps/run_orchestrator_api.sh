#!/usr/bin/env sh
set -eu
exec uvicorn apps.orchestrator.api.service:app --host 0.0.0.0 --port 8000
