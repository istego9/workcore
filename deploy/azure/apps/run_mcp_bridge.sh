#!/usr/bin/env sh
set -eu
exec uvicorn apps.orchestrator.mcp_bridge.service:app --host 0.0.0.0 --port 8002
