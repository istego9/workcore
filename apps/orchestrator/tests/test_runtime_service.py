import unittest

from apps.orchestrator.runtime import (
    Edge,
    Node,
    OrchestratorEngine,
    OrchestratorService,
    SimpleEvaluator,
    Workflow,
)


class OrchestratorServiceTests(unittest.IsolatedAsyncioTestCase):
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

        stored = service.store.list_events(run.id)
        self.assertTrue(len(stored) > 0)
        snapshot = service.store.get_snapshot(run.id)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.payload.get("status"), run.status)


if __name__ == "__main__":
    unittest.main()
