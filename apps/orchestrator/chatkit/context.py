from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Dict

from apps.orchestrator.chatkit.idempotency import IdempotencyStore
from apps.orchestrator.chatkit.runtime_service import ChatKitRuntimeService


@dataclass
class ChatKitContext:
    service: ChatKitRuntimeService
    run_store: Any
    tenant_id: str
    idempotency: Optional[IdempotencyStore] = None
    request_metadata: Optional[Dict[str, object]] = None
