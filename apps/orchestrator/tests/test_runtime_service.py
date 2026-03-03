import unittest
from unittest import mock

from apps.orchestrator.runtime import (
    Edge,
    Node,
    OrchestratorEngine,
    OrchestratorService,
    SimpleEvaluator,
    Workflow,
)


class OrchestratorServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_start_run_offloads_engine_execution_to_worker_thread(self):
        nodes = [
            Node("start", "start", {"defaults": {"count": 0}}),
            Node("out", "output", {"expression": "state['count']"}),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "out"),
            Edge("out", "end"),
        ]
        workflow = Workflow(
            id="wf_thread_offload",
            version_id="v1",
            nodes={node.id: node for node in nodes},
            edges=edges,
        )
        engine = OrchestratorEngine(workflow, SimpleEvaluator())
        service = OrchestratorService.create(engine)

        async def _to_thread_passthrough(func, *args, **kwargs):
            return func(*args, **kwargs)

        with mock.patch(
            "apps.orchestrator.runtime.service.asyncio.to_thread",
            new=mock.AsyncMock(side_effect=_to_thread_passthrough),
        ) as to_thread_mock:
            run = await service.start_run({})

        self.assertEqual(run.status, "COMPLETED")
        self.assertGreaterEqual(to_thread_mock.await_count, 1)
        first_fn = to_thread_mock.await_args_list[0].args[0]
        self.assertEqual(getattr(first_fn, "__name__", ""), "execute_until_blocked")

    async def test_service_publishes_events_and_snapshot(self):
        nodes = [
            Node("start", "start", {"defaults": {"count": 0}}),
            Node("out", "output", {"expression": "state['count']"}),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "out"),
            Edge("out", "end"),
        ]
        workflow = Workflow(
            id="wf_1",
            version_id="v1",
            nodes={node.id: node for node in nodes},
            edges=edges,
        )
        engine = OrchestratorEngine(workflow, SimpleEvaluator())
        service = OrchestratorService.create(engine)

        run = await service.start_run({})

        stored = await service.store.list_events(run.id)
        self.assertTrue(len(stored) > 0)
        snapshot = await service.store.get_snapshot(run.id)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.payload.get("status"), run.status)

    async def test_service_snapshot_applies_projection_from_run_metadata(self):
        nodes = [
            Node("start", "start"),
            Node("out", "output", {"value": {"result": {"claim_id": "clm_1", "decision": "approve"}}}),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "out"),
            Edge("out", "end"),
        ]
        workflow = Workflow(
            id="wf_projection",
            version_id="v1",
            nodes={node.id: node for node in nodes},
            edges=edges,
        )
        engine = OrchestratorEngine(workflow, SimpleEvaluator())
        service = OrchestratorService.create(engine)

        run = await service.start_run(
            {
                "documents": [
                    {
                        "doc_id": "doc_1",
                        "pages": [{"image_base64": "AAAA", "artifact_ref": "artf_1"}],
                    }
                ]
            },
            metadata={
                "state_exclude_paths": ["documents.pages.image_base64"],
                "output_include_paths": ["result.claim_id"],
            },
        )
        snapshot = await service.store.get_snapshot(run.id)
        self.assertIsNotNone(snapshot)
        state_page = snapshot.payload["state"]["documents"][0]["pages"][0]
        self.assertNotIn("image_base64", state_page)
        self.assertEqual(snapshot.payload["outputs"], {"result": {"claim_id": "clm_1"}})


if __name__ == "__main__":
    unittest.main()
