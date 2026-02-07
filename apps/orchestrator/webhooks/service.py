from __future__ import annotations

import asyncio
from contextlib import suppress
from inspect import isawaitable
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from apps.orchestrator.api.workflow_store import WorkflowConflictError, WorkflowNotFoundError
from apps.orchestrator.runtime.models import Event as RuntimeEvent, Run

from .dispatcher import DispatcherConfig, OutboundDispatcher
from .models import IdempotencyRecord, WebhookDelivery, WebhookSubscription
from .signing import verify_signature
from .store import InMemoryWebhookStore


@dataclass
class WebhookService:
    store: InMemoryWebhookStore
    dispatcher: OutboundDispatcher
    idempotency_ttl_s: int = 300
    poll_interval_s: float = 1.0
    _dispatch_task: Optional[asyncio.Task] = field(default=None, init=False, repr=False)

    @classmethod
    def create(cls) -> "WebhookService":
        return cls(store=InMemoryWebhookStore(), dispatcher=OutboundDispatcher())

    async def start_background_dispatcher(self) -> None:
        if self._dispatch_task and not self._dispatch_task.done():
            return
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())

    async def stop_background_dispatcher(self) -> None:
        if not self._dispatch_task:
            return
        self._dispatch_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._dispatch_task
        self._dispatch_task = None

    async def _dispatch_loop(self) -> None:
        while True:
            await self.process_due_deliveries()
            await asyncio.sleep(self.poll_interval_s)

    async def process_due_deliveries(self) -> None:
        now = time.time()
        for delivery in self.store.list_due_deliveries(now):
            subscription = self.store.get_subscription(delivery.subscription_id)
            if not subscription or not subscription.is_active:
                continue
            await self._attempt_delivery(subscription, delivery)

    def register_outbound(self, url: str, event_types: List[str], secret: Optional[str] = None) -> WebhookSubscription:
        subscription = WebhookSubscription(
            id=self._new_id("whsub"),
            url=url,
            event_types=event_types,
            secret=secret or self._new_id("whsec"),
        )
        self.store.add_subscription(subscription)
        return subscription

    def list_outbound(self) -> List[WebhookSubscription]:
        return self.store.list_subscriptions()

    def delete_outbound(self, sub_id: str) -> bool:
        return self.store.delete_subscription(sub_id)

    def register_inbound_key(self, integration_key: str, secret: str) -> None:
        self.store.set_inbound_key(integration_key, secret)

    async def handle_inbound(
        self,
        integration_key: str,
        headers: Dict[str, str],
        body: bytes,
        payload: Dict[str, Any],
        run_store: Any,
        runtime,
    ) -> Tuple[int, Dict[str, Any]]:
        async def _await_if_needed(value: Any) -> Any:
            if isawaitable(value):
                return await value
            return value

        metadata_payload = payload.get("metadata")
        tenant_id = None
        if isinstance(metadata_payload, dict):
            value = metadata_payload.get("tenant_id")
            if isinstance(value, str) and value:
                tenant_id = value
        if not tenant_id:
            header_tenant = headers.get("X-Tenant-Id") or headers.get("x-tenant-id")
            tenant_id = header_tenant or "local"

        async def _save_run(run: Run) -> None:
            try:
                result = run_store.save(run, tenant_id=tenant_id)
            except TypeError:
                result = run_store.save(run)
            await _await_if_needed(result)

        async def _get_run(run_id: str) -> Optional[Run]:
            try:
                result = run_store.get(run_id, tenant_id=tenant_id)
            except TypeError:
                result = run_store.get(run_id)
            loaded = await _await_if_needed(result)
            if loaded is None:
                return None
            return loaded

        inbound_key = self.store.get_inbound_key(integration_key)
        if not inbound_key:
            return 404, {"error": {"code": "NOT_FOUND", "message": "integration key not found"}}

        if not verify_signature(inbound_key.secret, headers, body):
            return 401, {"error": {"code": "UNAUTHORIZED", "message": "invalid signature"}}

        idempotency_key = headers.get("Idempotency-Key")
        if idempotency_key:
            record = self.store.get_idempotency(idempotency_key, scope=integration_key)
            if record:
                return 200, record.response

        action = payload.get("action")
        if action == "start_run":
            workflow_id = payload.get("workflow_id")
            if not workflow_id:
                return 400, {"error": {"code": "INVALID_ARGUMENT", "message": "workflow_id required"}}
            version_id = payload.get("version_id") or payload.get("workflow_version_id")
            metadata = payload.get("metadata")
            if metadata is None:
                metadata = {}
            if not isinstance(metadata, dict):
                return 400, {"error": {"code": "INVALID_ARGUMENT", "message": "metadata must be an object"}}
            metadata = dict(metadata)
            metadata.setdefault("tenant_id", tenant_id)
            try:
                run = await runtime.start_run(
                    workflow_id,
                    version_id,
                    payload.get("inputs", {}),
                    mode=payload.get("mode"),
                    metadata=metadata,
                )
            except WorkflowNotFoundError:
                return 404, {"error": {"code": "NOT_FOUND", "message": "workflow not found"}}
            except WorkflowConflictError as exc:
                return 400, {"error": {"code": "INVALID_ARGUMENT", "message": str(exc)}}
            await _save_run(run)
            response = {"run_id": run.id, "status": run.status}
        elif action == "resume_interrupt":
            run_id = payload.get("run_id")
            interrupt_id = payload.get("interrupt_id")
            if not run_id or not interrupt_id:
                return 400, {"error": {"code": "INVALID_ARGUMENT", "message": "run_id and interrupt_id required"}}
            run = await _get_run(run_id)
            if not run:
                return 404, {"error": {"code": "NOT_FOUND", "message": "run not found"}}
            try:
                await runtime.resume_interrupt(run, interrupt_id, payload.get("input"), payload.get("files"))
            except ValueError as exc:
                return 400, {"error": {"code": "INVALID_ARGUMENT", "message": str(exc)}}
            await _save_run(run)
            response = {"run_id": run.id, "status": run.status}
        else:
            return 400, {"error": {"code": "INVALID_ARGUMENT", "message": "invalid action"}}

        if idempotency_key:
            self.store.set_idempotency(
                IdempotencyRecord(
                    key=idempotency_key,
                    scope=integration_key,
                    response=response,
                    status="COMPLETED",
                    expires_at=time.time() + self.idempotency_ttl_s,
                )
            )

        return 202, response

    async def handle_events(self, run: Run, events: List[RuntimeEvent]) -> None:
        for event in events:
            event_type = None
            payload: Dict[str, Any] = {
                "run_id": run.id,
                "workflow_id": run.workflow_id,
                "version_id": run.version_id,
            }
            if event.type == "run_completed":
                event_type = "run_completed"
                payload["outputs"] = run.outputs
            elif event.type == "run_failed":
                event_type = "run_failed"
                payload["error"] = event.payload
            elif event.type == "node_failed":
                event_type = "node_failed"
                payload["node_id"] = event.node_id
                payload["error"] = event.payload
            elif event.type == "run_waiting_for_input":
                event_type = "interrupt_created"
                payload["interrupts"] = [
                    {"interrupt_id": intr.id, "node_id": intr.node_id, "type": intr.type}
                    for intr in run.interrupts.values()
                ]

            if event_type:
                await self.enqueue_delivery(event_type, payload)

    async def enqueue_delivery(self, event_type: str, payload: Dict[str, Any]) -> None:
        now = time.time()
        for subscription in self.store.list_subscriptions():
            if event_type not in subscription.event_types:
                continue
            delivery = WebhookDelivery(
                id=self._new_id("whd"),
                subscription_id=subscription.id,
                event_type=event_type,
                payload=payload,
                status="PENDING",
                attempt_count=0,
                next_retry_at=now,
            )
            self.store.add_delivery(delivery)
            await self._attempt_delivery(subscription, delivery)

    async def _attempt_delivery(self, subscription: WebhookSubscription, delivery: WebhookDelivery) -> None:
        if delivery.attempt_count >= self.dispatcher.config.max_attempts:
            delivery.status = "FAILED"
            delivery.last_error = "max_attempts_reached"
            self.store.update_delivery(delivery)
            return

        delivery.attempt_count += 1
        try:
            status = await self.dispatcher.send(subscription.url, delivery.payload, subscription.secret)
            if 200 <= status < 300:
                delivery.status = "SUCCESS"
            else:
                delivery.status = "FAILED"
                delivery.last_error = f"status_{status}"
                delivery.next_retry_at = time.time() + self._backoff(delivery.attempt_count)
        except Exception as exc:
            delivery.status = "FAILED"
            delivery.last_error = str(exc)
            delivery.next_retry_at = time.time() + self._backoff(delivery.attempt_count)

        self.store.update_delivery(delivery)

    def _backoff(self, attempt: int) -> float:
        return self.dispatcher.config.base_backoff_s * (2 ** (attempt - 1))

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8]}"
