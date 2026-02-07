from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator, Dict, Optional, Protocol

from .events import EventEnvelope


class EventBus(Protocol):
    async def publish(self, event: EventEnvelope) -> None:
        ...

    async def subscribe(self, run_id: str) -> AsyncIterator[EventEnvelope]:
        ...


@dataclass
class InMemoryEventBus:
    subscribers: Dict[str, list[asyncio.Queue]]

    def __init__(self) -> None:
        self.subscribers = {}

    async def publish(self, event: EventEnvelope) -> None:
        for queue in list(self.subscribers.get(event.run_id, [])):
            await queue.put(event)

    async def subscribe(self, run_id: str) -> AsyncIterator[EventEnvelope]:
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.setdefault(run_id, []).append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            subscribers = self.subscribers.get(run_id, [])
            if queue in subscribers:
                subscribers.remove(queue)
