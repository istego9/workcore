from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import IdempotencyRecord, InboundKey, WebhookDelivery, WebhookSubscription


@dataclass
class InMemoryWebhookStore:
    subscriptions: Dict[str, WebhookSubscription] = field(default_factory=dict)
    deliveries: Dict[str, WebhookDelivery] = field(default_factory=dict)
    inbound_keys: Dict[str, InboundKey] = field(default_factory=dict)
    idempotency: Dict[str, IdempotencyRecord] = field(default_factory=dict)

    def add_subscription(self, subscription: WebhookSubscription) -> None:
        self.subscriptions[subscription.id] = subscription

    def list_subscriptions(self) -> List[WebhookSubscription]:
        return [s for s in self.subscriptions.values() if s.is_active]

    def get_subscription(self, sub_id: str) -> Optional[WebhookSubscription]:
        return self.subscriptions.get(sub_id)

    def delete_subscription(self, sub_id: str) -> bool:
        sub = self.subscriptions.get(sub_id)
        if not sub:
            return False
        sub.is_active = False
        return True

    def add_delivery(self, delivery: WebhookDelivery) -> None:
        self.deliveries[delivery.id] = delivery

    def update_delivery(self, delivery: WebhookDelivery) -> None:
        self.deliveries[delivery.id] = delivery

    def list_due_deliveries(self, now_ts: float) -> List[WebhookDelivery]:
        return [
            d
            for d in self.deliveries.values()
            if d.status in ("PENDING", "FAILED") and d.next_retry_at <= now_ts
        ]

    def set_inbound_key(self, integration_key: str, secret: str) -> None:
        self.inbound_keys[integration_key] = InboundKey(integration_key=integration_key, secret=secret)

    def get_inbound_key(self, integration_key: str) -> Optional[InboundKey]:
        key = self.inbound_keys.get(integration_key)
        if not key or not key.is_active:
            return None
        return key

    def get_idempotency(self, key: str, scope: str) -> Optional[IdempotencyRecord]:
        record = self.idempotency.get(f"{scope}:{key}")
        if not record:
            return None
        if record.expires_at < time.time():
            self.idempotency.pop(f"{scope}:{key}", None)
            return None
        return record

    def set_idempotency(self, record: IdempotencyRecord) -> None:
        self.idempotency[f"{record.scope}:{record.key}"] = record
