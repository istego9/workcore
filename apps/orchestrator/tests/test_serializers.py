import unittest

from apps.orchestrator.api.serializers import run_to_dict
from apps.orchestrator.runtime.models import NodeRun, Run


class SerializerTests(unittest.TestCase):
    def test_run_to_dict_backfills_mock_usage(self):
        run = Run(
            id="run_1",
            workflow_id="wf_1",
            version_id="v1",
            status="COMPLETED",
            inputs={},
            state={},
            node_runs={
                "agent": NodeRun(
                    node_id="agent",
                    status="RESOLVED",
                    output={
                        "mock": True,
                        "resolved_instructions": "Extract fields from text",
                        "resolved_input": "user payload",
                    },
                    usage=None,
                )
            },
        )

        payload = run_to_dict(run)
        node_runs = payload.get("node_runs") or []
        self.assertEqual(len(node_runs), 1)
        usage = node_runs[0].get("usage")
        self.assertIsInstance(usage, dict)
        self.assertEqual(usage.get("provider"), "mock")
        self.assertEqual(usage.get("estimated"), True)
        self.assertGreater(usage.get("total_tokens", 0), 0)

    def test_run_to_dict_applies_projection_from_metadata(self):
        run = Run(
            id="run_projection",
            workflow_id="wf_1",
            version_id="v1",
            status="COMPLETED",
            inputs={},
            state={
                "documents": [
                    {
                        "doc_id": "doc_1",
                        "pages": [{"image_base64": "AAAA", "artifact_ref": "artf_1"}],
                    }
                ]
            },
            outputs={"result": {"claim_id": "clm_1", "decision": "approve"}},
            metadata={
                "state_exclude_paths": ["documents.pages.image_base64"],
                "output_include_paths": ["result.claim_id"],
            },
        )

        payload = run_to_dict(run)
        page = payload["state"]["documents"][0]["pages"][0]
        self.assertNotIn("image_base64", page)
        self.assertEqual(page.get("artifact_ref"), "artf_1")
        self.assertEqual(payload.get("outputs"), {"result": {"claim_id": "clm_1"}})


if __name__ == "__main__":
    unittest.main()
