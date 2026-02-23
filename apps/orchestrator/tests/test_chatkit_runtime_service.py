import unittest
from unittest import mock

from apps.orchestrator.chatkit.runtime_service import ChatKitRuntimeService
from apps.orchestrator.runtime import Edge, Node, SimpleEvaluator, Workflow
from apps.orchestrator.streaming import EventPublisher, InMemoryEventBus, InMemoryEventStore


class ChatKitRuntimeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_run_offloads_engine_execution_to_worker_thread(self):
        nodes = [
            Node("start", "start"),
            Node("end", "end"),
        ]
        edges = [Edge("start", "end")]
        workflow = Workflow(
            id="wf_chatkit_thread_offload",
            version_id="v1",
            nodes={node.id: node for node in nodes},
            edges=edges,
        )
        store = InMemoryEventStore()
        bus = InMemoryEventBus()
        publisher = EventPublisher(store, bus)

        async def loader(workflow_id: str, version_id: str | None, tenant_id: str):
            if workflow_id != workflow.id:
                raise RuntimeError("unknown workflow")
            return workflow

        service = ChatKitRuntimeService(
            publisher=publisher,
            store=store,
            bus=bus,
            evaluator=SimpleEvaluator(),
            workflow_loader=loader,
        )

        async def _to_thread_passthrough(func, *args, **kwargs):
            return func(*args, **kwargs)

        with mock.patch(
            "apps.orchestrator.chatkit.runtime_service.asyncio.to_thread",
            new=mock.AsyncMock(side_effect=_to_thread_passthrough),
        ) as to_thread_mock:
            run = await service.start_run(workflow.id, workflow.version_id, {"seed": "ok"}, tenant_id="tenant_1")

        self.assertEqual(run.status, "COMPLETED")
        self.assertGreaterEqual(to_thread_mock.await_count, 1)
        first_fn = to_thread_mock.await_args_list[0].args[0]
        self.assertEqual(getattr(first_fn, "__name__", ""), "execute_until_blocked")


if __name__ == "__main__":
    unittest.main()
