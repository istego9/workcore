from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from .events import EventEnvelope


@dataclass
class KafkaConfig:
    bootstrap_servers: str
    topic: str
    group_id: str


class KafkaEventBus:
    def __init__(self, config: KafkaConfig) -> None:
        self.config = config
        self._producer: Optional[AIOKafkaProducer] = None

    async def start(self) -> None:
        if self._producer is None:
            self._producer = AIOKafkaProducer(bootstrap_servers=self.config.bootstrap_servers)
            await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish(self, event: EventEnvelope) -> None:
        if self._producer is None:
            raise RuntimeError("KafkaEventBus not started")
        payload = json.dumps(
            {
                "id": event.id,
                "type": event.type,
                "run_id": event.run_id,
                "workflow_id": event.workflow_id,
                "version_id": event.version_id,
                "node_id": event.node_id,
                "payload": event.payload,
                "timestamp": event.timestamp,
                "sequence": event.sequence,
                "correlation_id": event.correlation_id,
                "trace_id": event.trace_id,
                "tenant_id": event.tenant_id,
                "project_id": event.project_id,
                "import_run_id": event.import_run_id,
            }
        ).encode("utf-8")
        await self._producer.send_and_wait(
            self.config.topic,
            key=event.run_id.encode("utf-8"),
            value=payload,
        )

    async def subscribe(self, run_id: str) -> AsyncIterator[EventEnvelope]:
        consumer = AIOKafkaConsumer(
            self.config.topic,
            bootstrap_servers=self.config.bootstrap_servers,
            group_id=self.config.group_id,
            enable_auto_commit=True,
            auto_offset_reset="earliest",
        )
        await consumer.start()
        try:
            async for message in consumer:
                if not message.value:
                    continue
                data = json.loads(message.value.decode("utf-8"))
                if data.get("run_id") != run_id:
                    continue
                yield EventEnvelope(
                    id=data["id"],
                    type=data["type"],
                    run_id=data["run_id"],
                    workflow_id=data["workflow_id"],
                    version_id=data["version_id"],
                    node_id=data.get("node_id"),
                    payload=data.get("payload", {}),
                    timestamp=data["timestamp"],
                    sequence=int(data.get("sequence") or 0),
                    correlation_id=data.get("correlation_id"),
                    trace_id=data.get("trace_id"),
                    tenant_id=data.get("tenant_id"),
                    project_id=data.get("project_id"),
                    import_run_id=data.get("import_run_id"),
                )
        finally:
            await consumer.stop()
