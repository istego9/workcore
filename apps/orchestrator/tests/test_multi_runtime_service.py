import unittest
from unittest import mock

from apps.orchestrator.runtime import Edge, MultiWorkflowRuntimeService, Node, SimpleEvaluator, Workflow


class MultiWorkflowRuntimeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_run_offloads_engine_execution_to_worker_thread(self):
        nodes = [
            Node("start", "start"),
            Node("end", "end"),
        ]
        edges = [Edge("start", "end")]
        workflow = Workflow(
            id="wf_multi_thread_offload",
            version_id="v1",
            nodes={node.id: node for node in nodes},
            edges=edges,
        )

        async def loader(workflow_id: str, version_id: str | None, tenant_id: str | None = None):
            if workflow_id != workflow.id:
                raise RuntimeError("unknown workflow")
            return workflow

        service = MultiWorkflowRuntimeService.create(workflow_loader=loader, evaluator=SimpleEvaluator())

        async def _to_thread_passthrough(func, *args, **kwargs):
            return func(*args, **kwargs)

        with mock.patch(
            "apps.orchestrator.runtime.multi_service.asyncio.to_thread",
            new=mock.AsyncMock(side_effect=_to_thread_passthrough),
        ) as to_thread_mock:
            run = await service.start_run(workflow.id, workflow.version_id, inputs={"seed": "ok"})

        self.assertEqual(run.status, "COMPLETED")
        self.assertGreaterEqual(to_thread_mock.await_count, 1)
        first_fn = to_thread_mock.await_args_list[0].args[0]
        self.assertEqual(getattr(first_fn, "__name__", ""), "execute_until_blocked")


if __name__ == "__main__":
    unittest.main()
