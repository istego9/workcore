from __future__ import annotations

from apps.orchestrator.api.app import create_app, validate_runtime_security_env


validate_runtime_security_env()
app = create_app()
