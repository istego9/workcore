import unittest
from datetime import datetime, timezone

from apps.orchestrator.api.ledger_store import RunLedgerEntry
from apps.orchestrator.api.serializers import run_ledger_entry_to_dict, run_to_dict
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

    def test_run_to_dict_includes_legacy_failure_aliases(self):
        run = Run(
            id="run_failed",
            workflow_id="wf_1",
            version_id="v1",
            status="FAILED",
            inputs={},
            state={},
            outputs=None,
            node_runs={
                "start": NodeRun(node_id="start", status="RESOLVED"),
                "infer_fields": NodeRun(
                    node_id="infer_fields",
                    status="ERROR",
                    last_error="Too Many Requests",
                ),
            },
        )

        payload = run_to_dict(run)
        self.assertEqual(payload.get("error"), "Too Many Requests")
        self.assertEqual(payload.get("last_error"), "Too Many Requests")
        self.assertEqual(payload.get("failed_node_id"), "infer_fields")
        self.assertEqual(payload.get("node_states"), payload.get("node_runs"))

    def test_run_ledger_entry_to_dict_exposes_node_id_alias(self):
        entry = RunLedgerEntry(
            ledger_id="led_1",
            tenant_id="local",
            run_id="run_1",
            workflow_id="wf_1",
            version_id="v1",
            step_id="infer_fields",
            capability_id=None,
            capability_version=None,
            status="ERROR",
            event_type="node_failed",
            decision=None,
            artifacts=[],
            payload={"error": "Too Many Requests"},
            timestamp=datetime(2026, 3, 4, 0, 0, 0, tzinfo=timezone.utc),
        )

        payload = run_ledger_entry_to_dict(entry)
        self.assertEqual(payload.get("step_id"), "infer_fields")
        self.assertEqual(payload.get("node_id"), "infer_fields")


if __name__ == "__main__":
    unittest.main()
