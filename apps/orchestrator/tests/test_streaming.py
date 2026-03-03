import asyncio
import unittest

from apps.orchestrator.runtime.models import Event as RuntimeEvent
from apps.orchestrator.streaming import (
    EventPublisher,
    InMemoryEventBus,
    InMemoryEventStore,
)


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_publisher_writes_store_and_bus(self):
        store = InMemoryEventStore()
        bus = InMemoryEventBus()
        publisher = EventPublisher(store, bus)

        events = [
            RuntimeEvent(
                type="node_completed",
                run_id="run_1",
                workflow_id="wf_1",
                version_id="v1",
                node_id="n1",
                payload={"ok": True},
            )
        ]

        await publisher.publish(events)

        stored = await store.list_events("run_1")
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].type, "node_completed")
        self.assertEqual(stored[0].sequence, 1)

        async def consume():
            async for evt in bus.subscribe("run_1"):
                return evt

        task = asyncio.create_task(consume())
        await asyncio.sleep(0)
        await bus.publish(stored[0])
        evt = await task
        self.assertEqual(evt.id, stored[0].id)


if __name__ == "__main__":
    unittest.main()
