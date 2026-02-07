from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class WebhookSubscription:
    id: str
    url: str
    event_types: List[str]
    secret: str
    is_active: bool = True


@dataclass
class WebhookDelivery:
    id: str
    subscription_id: str
    event_type: str
    payload: Dict[str, any]
    status: str
    attempt_count: int
    next_retry_at: float
    last_error: Optional[str] = None


@dataclass
class InboundKey:
    integration_key: str
    secret: str
    is_active: bool = True


@dataclass
class IdempotencyRecord:
    key: str
    scope: str
    response: Dict[str, any]
    status: str
    expires_at: float
