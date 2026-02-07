import json
import unittest

import httpx

from apps.orchestrator.integration.hq21_client import WorkCoreApiError, WorkCoreClient


class WorkCoreClientTests(unittest.TestCase):
    def test_start_run_sends_transparent_headers_and_metadata(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["headers"] = dict(request.headers)
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                201,
                json={
                    "run_id": "run_1",
                    "status": "RUNNING",
                    "correlation_id": "corr_fixed",
                    "trace_id": "trace_fixed",
                    "tenant_id": "tenant_a",
                    "project_id": "proj_1",
                    "import_run_id": "imp_1",
                },
            )

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        sdk = WorkCoreClient("http://workcore.local", bearer_token="tok", client=client)
        try:
            result = sdk.start_run(
                "wf_1",
                tenant_id="tenant_a",
                project_id="proj_1",
                import_run_id="imp_1",
                inputs={"document_text": "text"},
                mode="async",
                correlation_id="corr_fixed",
                trace_id="trace_fixed",
                idempotency_key="idem_1",
            )
        finally:
            sdk.close()

        self.assertEqual(result["run_id"], "run_1")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/workflows/wf_1/runs")
        self.assertEqual(captured["headers"]["x-tenant-id"], "tenant_a")
        self.assertEqual(captured["headers"]["x-correlation-id"], "corr_fixed")
        self.assertEqual(captured["headers"]["x-trace-id"], "trace_fixed")
        self.assertEqual(captured["headers"]["idempotency-key"], "idem_1")
        self.assertEqual(captured["headers"]["authorization"], "Bearer tok")
        self.assertEqual(captured["payload"]["metadata"]["tenant_id"], "tenant_a")
        self.assertEqual(captured["payload"]["metadata"]["project_id"], "proj_1")
        self.assertEqual(captured["payload"]["metadata"]["import_run_id"], "imp_1")

    def test_error_envelope_is_raised_as_workcore_error(self):
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404,
                json={
                    "error": {"code": "NOT_FOUND", "message": "run not found"},
                    "correlation_id": "corr_404",
                },
            )

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        sdk = WorkCoreClient("http://workcore.local", client=client)
        try:
            with self.assertRaises(WorkCoreApiError) as ctx:
                sdk.get_run("run_missing", tenant_id="tenant_a")
        finally:
            sdk.close()

        error = ctx.exception
        self.assertEqual(error.code, "NOT_FOUND")
        self.assertEqual(error.status_code, 404)
        self.assertEqual(error.correlation_id, "corr_404")


if __name__ == "__main__":
    unittest.main()
