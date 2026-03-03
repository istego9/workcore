from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol
import uuid

import asyncpg

from .models import IdempotencyRecord, InboundKey, WebhookDelivery, WebhookSubscription


class WebhookStore(Protocol):
    async def add_subscription(self, subscription: WebhookSubscription) -> None:
        ...

    async def list_subscriptions(self) -> List[WebhookSubscription]:
        ...

    async def get_subscription(self, sub_id: str) -> Optional[WebhookSubscription]:
        ...

    async def delete_subscription(self, sub_id: str) -> bool:
        ...

    async def add_delivery(self, delivery: WebhookDelivery) -> None:
        ...

    async def update_delivery(self, delivery: WebhookDelivery) -> None:
        ...

    async def list_due_deliveries(self, now_ts: float) -> List[WebhookDelivery]:
        ...

    async def set_inbound_key(self, integration_key: str, secret: str) -> None:
        ...

    async def get_inbound_key(self, integration_key: str) -> Optional[InboundKey]:
        ...

    async def get_idempotency(self, key: str, scope: str) -> Optional[IdempotencyRecord]:
        ...

    async def set_idempotency(self, record: IdempotencyRecord) -> None:
        ...


@dataclass
class InMemoryWebhookStore:
    subscriptions: Dict[str, WebhookSubscription] = field(default_factory=dict)
    deliveries: Dict[str, WebhookDelivery] = field(default_factory=dict)
    inbound_keys: Dict[str, InboundKey] = field(default_factory=dict)
    idempotency: Dict[str, IdempotencyRecord] = field(default_factory=dict)

    async def add_subscription(self, subscription: WebhookSubscription) -> None:
        self.subscriptions[subscription.id] = subscription

    async def list_subscriptions(self) -> List[WebhookSubscription]:
        return [s for s in self.subscriptions.values() if s.is_active]

    async def get_subscription(self, sub_id: str) -> Optional[WebhookSubscription]:
        return self.subscriptions.get(sub_id)

    async def delete_subscription(self, sub_id: str) -> bool:
        sub = self.subscriptions.get(sub_id)
        if not sub:
            return False
        sub.is_active = False
        return True

    async def add_delivery(self, delivery: WebhookDelivery) -> None:
        self.deliveries[delivery.id] = delivery

    async def update_delivery(self, delivery: WebhookDelivery) -> None:
        self.deliveries[delivery.id] = delivery

    async def list_due_deliveries(self, now_ts: float) -> List[WebhookDelivery]:
        return [
            d
            for d in self.deliveries.values()
            if d.status in ("PENDING", "FAILED") and d.next_retry_at <= now_ts
        ]

    async def set_inbound_key(self, integration_key: str, secret: str) -> None:
        self.inbound_keys[integration_key] = InboundKey(integration_key=integration_key, secret=secret)

    async def get_inbound_key(self, integration_key: str) -> Optional[InboundKey]:
        key = self.inbound_keys.get(integration_key)
        if not key or not key.is_active:
            return None
        return key

    async def get_idempotency(self, key: str, scope: str) -> Optional[IdempotencyRecord]:
        record = self.idempotency.get(f"{scope}:{key}")
        if not record:
            return None
        if record.expires_at < time.time():
            self.idempotency.pop(f"{scope}:{key}", None)
            return None
        return record

    async def set_idempotency(self, record: IdempotencyRecord) -> None:
        self.idempotency[f"{record.scope}:{record.key}"] = record


def _jsonb(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _parse_dict(value: Any) -> Dict[str, Any]:
    parsed = _parse_json(value)
    if isinstance(parsed, dict):
        return parsed
    return {}


def _to_epoch(value: Any, fallback: float = 0.0) -> float:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    return fallback


@dataclass
class PostgresWebhookStore:
    pool: asyncpg.Pool
    tenant_id: str = "local"

    async def add_subscription(self, subscription: WebhookSubscription) -> None:
        await self.pool.execute(
            """
            insert into webhook_subscriptions (
                id, tenant_id, url, event_types, secret_ref, is_active, created_at, updated_at
            )
            values ($1, $2, $3, $4::text[], $5, $6, now(), now())
            on conflict (id) do update
            set url = excluded.url,
                event_types = excluded.event_types,
                secret_ref = excluded.secret_ref,
                is_active = excluded.is_active,
                updated_at = now()
            """,
            subscription.id,
            self.tenant_id,
            subscription.url,
            list(subscription.event_types),
            subscription.secret,
            subscription.is_active,
        )

    async def list_subscriptions(self) -> List[WebhookSubscription]:
        rows = await self.pool.fetch(
            """
            select id, url, event_types, secret_ref, is_active
            from webhook_subscriptions
            where tenant_id = $1 and is_active = true
            order by created_at asc
            """,
            self.tenant_id,
        )
        return [
            WebhookSubscription(
                id=str(row["id"]),
                url=str(row["url"]),
                event_types=[str(item) for item in (row["event_types"] or [])],
                secret=str(row["secret_ref"]),
                is_active=bool(row["is_active"]),
            )
            for row in rows
        ]

    async def get_subscription(self, sub_id: str) -> Optional[WebhookSubscription]:
        row = await self.pool.fetchrow(
            """
            select id, url, event_types, secret_ref, is_active
            from webhook_subscriptions
            where id = $1 and tenant_id = $2
            limit 1
            """,
            sub_id,
            self.tenant_id,
        )
        if not row:
            return None
        return WebhookSubscription(
            id=str(row["id"]),
            url=str(row["url"]),
            event_types=[str(item) for item in (row["event_types"] or [])],
            secret=str(row["secret_ref"]),
            is_active=bool(row["is_active"]),
        )

    async def delete_subscription(self, sub_id: str) -> bool:
        result = await self.pool.execute(
            """
            update webhook_subscriptions
            set is_active = false, updated_at = now()
            where id = $1 and tenant_id = $2 and is_active = true
            """,
            sub_id,
            self.tenant_id,
        )
        return result != "UPDATE 0"

    async def add_delivery(self, delivery: WebhookDelivery) -> None:
        await self.pool.execute(
            """
            insert into webhook_deliveries (
                id, subscription_id, event_id, event_type, payload, status,
                attempt_count, last_error, next_retry_at, created_at, updated_at
            )
            values (
                $1, $2, null, $3, $4::jsonb, $5,
                $6, $7, to_timestamp($8), now(), now()
            )
            on conflict (id) do update
            set event_type = excluded.event_type,
                payload = excluded.payload,
                status = excluded.status,
                attempt_count = excluded.attempt_count,
                last_error = excluded.last_error,
                next_retry_at = excluded.next_retry_at,
                updated_at = now()
            """,
            delivery.id,
            delivery.subscription_id,
            delivery.event_type,
            _jsonb(delivery.payload),
            delivery.status,
            delivery.attempt_count,
            delivery.last_error,
            float(delivery.next_retry_at),
        )

    async def update_delivery(self, delivery: WebhookDelivery) -> None:
        await self.pool.execute(
            """
            update webhook_deliveries
            set status = $2,
                attempt_count = $3,
                last_error = $4,
                next_retry_at = to_timestamp($5),
                updated_at = now()
            where id = $1
            """,
            delivery.id,
            delivery.status,
            delivery.attempt_count,
            delivery.last_error,
            float(delivery.next_retry_at),
        )

    async def list_due_deliveries(self, now_ts: float) -> List[WebhookDelivery]:
        rows = await self.pool.fetch(
            """
            select d.id, d.subscription_id, d.event_type, d.payload, d.status,
                   d.attempt_count, d.next_retry_at, d.last_error
            from webhook_deliveries d
            join webhook_subscriptions s on s.id = d.subscription_id
            where s.tenant_id = $1
              and d.status in ('PENDING', 'FAILED')
              and d.next_retry_at <= to_timestamp($2)
            order by d.next_retry_at asc
            """,
            self.tenant_id,
            float(now_ts),
        )
        deliveries: List[WebhookDelivery] = []
        for row in rows:
            deliveries.append(
                WebhookDelivery(
                    id=str(row["id"]),
                    subscription_id=str(row["subscription_id"]),
                    event_type=str(row["event_type"]),
                    payload=_parse_dict(row["payload"]),
                    status=str(row["status"]),
                    attempt_count=int(row["attempt_count"] or 0),
                    next_retry_at=_to_epoch(row["next_retry_at"], fallback=now_ts),
                    last_error=str(row["last_error"]) if row["last_error"] is not None else None,
                )
            )
        return deliveries

    async def set_inbound_key(self, integration_key: str, secret: str) -> None:
        record_id = f"whk_{uuid.uuid4().hex[:8]}"
        await self.pool.execute(
            """
            insert into webhook_inbound_keys (
                id, tenant_id, integration_key, secret_ref, is_active, created_at, updated_at
            )
            values ($1, $2, $3, $4, true, now(), now())
            on conflict (integration_key) do update
            set secret_ref = excluded.secret_ref,
                is_active = true,
                updated_at = now()
            """,
            record_id,
            self.tenant_id,
            integration_key,
            secret,
        )

    async def get_inbound_key(self, integration_key: str) -> Optional[InboundKey]:
        row = await self.pool.fetchrow(
            """
            select integration_key, secret_ref, is_active
            from webhook_inbound_keys
            where integration_key = $1
            limit 1
            """,
            integration_key,
        )
        if not row or not bool(row["is_active"]):
            return None
        return InboundKey(
            integration_key=str(row["integration_key"]),
            secret=str(row["secret_ref"]),
            is_active=bool(row["is_active"]),
        )

    async def get_idempotency(self, key: str, scope: str) -> Optional[IdempotencyRecord]:
        row = await self.pool.fetchrow(
            """
            select idempotency_key, scope, response_body, status, expires_at
            from idempotency_keys
            where tenant_id = $1 and idempotency_key = $2 and scope = $3
            limit 1
            """,
            self.tenant_id,
            key,
            scope,
        )
        if not row:
            return None
        expires_at = row["expires_at"]
        if isinstance(expires_at, datetime):
            if expires_at <= datetime.now(timezone.utc):
                await self.pool.execute(
                    """
                    delete from idempotency_keys
                    where tenant_id = $1 and idempotency_key = $2 and scope = $3
                    """,
                    self.tenant_id,
                    key,
                    scope,
                )
                return None
        payload = _parse_dict(row["response_body"])
        if str(row["status"]) != "COMPLETED":
            return None
        return IdempotencyRecord(
            key=str(row["idempotency_key"]),
            scope=str(row["scope"]),
            response=payload,
            status=str(row["status"]),
            expires_at=_to_epoch(expires_at, fallback=time.time()),
        )

    async def set_idempotency(self, record: IdempotencyRecord) -> None:
        request_hash = hashlib.sha256(f"{record.scope}:{record.key}".encode("utf-8")).hexdigest()
        await self.pool.execute(
            """
            insert into idempotency_keys (
                id, tenant_id, idempotency_key, scope, request_hash,
                response_body, status, expires_at, created_at
            )
            values ($1, $2, $3, $4, $5, $6::jsonb, $7, to_timestamp($8), now())
            on conflict (tenant_id, idempotency_key, scope) do update
            set request_hash = excluded.request_hash,
                response_body = excluded.response_body,
                status = excluded.status,
                expires_at = excluded.expires_at
            """,
            f"idem_{uuid.uuid4().hex[:10]}",
            self.tenant_id,
            record.key,
            record.scope,
            request_hash,
            _jsonb(record.response),
            record.status,
            float(record.expires_at),
        )
