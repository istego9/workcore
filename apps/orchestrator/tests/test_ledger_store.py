import unittest

from apps.orchestrator.api.ledger_store import runtime_events_to_ledger_entries
from apps.orchestrator.runtime.models import Event, NodeRun, Run


class RunLedgerProjectionTests(unittest.TestCase):
    def test_run_failed_payload_is_enriched_with_fallback_node_diagnostics(self):
        run = Run(
            id="run_1",
            workflow_id="wf_1",
            version_id="v1",
            status="FAILED",
            inputs={},
            state={},
            outputs=None,
            node_runs={
                "classify": NodeRun(
                    node_id="classify",
                    status="ERROR",
                    last_error="classification timeout",
                    trace_id="trace_node_1",
                )
            },
            metadata={"tenant_id": "tenant_a", "correlation_id": "corr_1"},
        )
        events = [
            Event(
                type="run_failed",
                run_id=run.id,
                workflow_id=run.workflow_id,
                version_id=run.version_id,
                node_id=None,
                payload=None,
                metadata=dict(run.metadata or {}),
            )
        ]

        entries = runtime_events_to_ledger_entries(run, events)

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.status, "FAILED")
        self.assertEqual(entry.step_id, "classify")
        self.assertEqual(entry.payload.get("node_id"), "classify")
        self.assertEqual(entry.payload.get("error"), "classification timeout")
        self.assertEqual(entry.payload.get("trace_id"), "trace_node_1")
        self.assertEqual(entry.payload.get("correlation_id"), "corr_1")


if __name__ == "__main__":
    unittest.main()
