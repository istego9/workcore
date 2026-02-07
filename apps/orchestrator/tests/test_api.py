import asyncio
import os
import unittest

from starlette.testclient import TestClient

from apps.orchestrator.api import create_app
from apps.orchestrator.api.workflow_store import InMemoryWorkflowStore
from apps.orchestrator.streaming.sse import _event_stream


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.workflow_store = InMemoryWorkflowStore()
        self.client = TestClient(create_app(workflow_store=self.workflow_store))

    def _create_workflow(self, headers=None):
        draft = {
            "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}],
            "edges": [{"source": "start", "target": "end"}],
            "variables_schema": {},
        }
        response = self.client.post("/workflows", json={"name": "Test workflow", "draft": draft}, headers=headers)
        self.assertEqual(response.status_code, 201)
        workflow_id = response.json()["workflow_id"]

        publish_response = self.client.post(f"/workflows/{workflow_id}/publish", headers=headers)
        self.assertEqual(publish_response.status_code, 200)
        version_id = publish_response.json()["version_id"]
        return workflow_id, version_id

    def test_start_and_get_run(self):
        workflow_id, _ = self._create_workflow()
        response = self.client.post(f"/workflows/{workflow_id}/runs", json={"inputs": {}})
        self.assertEqual(response.status_code, 201)
        run_id = response.json()["run_id"]
        self.assertEqual(response.json().get("mode"), "live")

        get_response = self.client.get(f"/runs/{run_id}")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["run_id"], run_id)

    def test_start_run_test_mode(self):
        workflow_id, _ = self._create_workflow()
        response = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={"inputs": {}, "mode": "test"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json().get("mode"), "test")

    def test_start_run_exposes_transparent_metadata(self):
        headers = {
            "X-Correlation-Id": "corr_fixed",
            "X-Trace-Id": "trace_fixed",
            "X-Tenant-Id": "tenant_demo",
        }
        workflow_id, _ = self._create_workflow(headers=headers)
        response = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={
                "inputs": {},
                "metadata": {
                    "project_id": "proj_1",
                    "import_run_id": "imp_1",
                    "user_id": "user_7",
                },
            },
            headers=headers,
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload.get("correlation_id"), "corr_fixed")
        self.assertEqual(payload.get("trace_id"), "trace_fixed")
        self.assertEqual(payload.get("tenant_id"), "tenant_demo")
        self.assertEqual(payload.get("project_id"), "proj_1")
        self.assertEqual(payload.get("import_run_id"), "imp_1")
        self.assertEqual(payload.get("metadata", {}).get("user_id"), "user_7")

        run_id = payload["run_id"]
        get_response = self.client.get(f"/runs/{run_id}", headers=headers)
        self.assertEqual(get_response.status_code, 200)
        loaded = get_response.json()
        self.assertEqual(loaded.get("metadata", {}).get("tenant_id"), "tenant_demo")
        self.assertEqual(loaded.get("metadata", {}).get("trace_id"), "trace_fixed")

    def test_start_run_rejects_non_object_inputs(self):
        workflow_id, _ = self._create_workflow()
        response = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={"inputs": ["bad"]},
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENT")

    def test_start_run_idempotency_key_reuses_response(self):
        workflow_id, _ = self._create_workflow()
        headers = {"Idempotency-Key": "idem_run_1"}
        first = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={"inputs": {}},
            headers=headers,
        )
        second = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={"inputs": {}},
            headers=headers,
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json()["run_id"], second.json()["run_id"])

    def test_sse_snapshot(self):
        workflow_id, _ = self._create_workflow()
        response = self.client.post(f"/workflows/{workflow_id}/runs", json={"inputs": {}})
        run_id = response.json()["run_id"]
        runtime = self.client.app.state.runtime

        async def read_snapshot():
            gen = _event_stream(
                run_id,
                runtime.store,
                runtime.bus,
                None,
                runtime.store.get_snapshot,
            )
            return await gen.__anext__()

        snapshot = asyncio.run(read_snapshot())
        self.assertIn("event: snapshot", snapshot)

    def test_sse_snapshot_does_not_replay_old_events(self):
        workflow_id, _ = self._create_workflow()
        response = self.client.post(f"/workflows/{workflow_id}/runs", json={"inputs": {}})
        run_id = response.json()["run_id"]
        runtime = self.client.app.state.runtime

        async def read_snapshot_and_poll():
            gen = _event_stream(
                run_id,
                runtime.store,
                runtime.bus,
                None,
                runtime.store.get_snapshot,
            )
            try:
                first = await asyncio.wait_for(gen.__anext__(), timeout=0.5)
                second = None
                try:
                    second = await asyncio.wait_for(gen.__anext__(), timeout=0.1)
                except asyncio.TimeoutError:
                    second = None
                return first, second
            finally:
                await gen.aclose()

        first, second = asyncio.run(read_snapshot_and_poll())
        self.assertIn("event: snapshot", first)
        self.assertIsNone(second)

    def test_workflow_create_and_publish(self):
        workflow_id, version_id = self._create_workflow()
        self.assertTrue(workflow_id)
        self.assertTrue(version_id)

    def test_publish_rejects_invalid_draft(self):
        bad_draft = {"nodes": [{"id": "only", "type": "set_state"}], "edges": []}
        response = self.client.post("/workflows", json={"name": "Invalid workflow", "draft": bad_draft})
        self.assertEqual(response.status_code, 201)
        workflow_id = response.json()["workflow_id"]

        publish_response = self.client.post(f"/workflows/{workflow_id}/publish")
        self.assertEqual(publish_response.status_code, 400)
        error = publish_response.json()["error"]
        self.assertEqual(error["code"], "INVALID_ARGUMENT")

    def test_list_workflows(self):
        draft = {
            "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}],
            "edges": [{"source": "start", "target": "end"}],
            "variables_schema": {},
        }
        response_a = self.client.post("/workflows", json={"name": "List A", "draft": draft})
        response_b = self.client.post("/workflows", json={"name": "List B", "draft": draft})
        self.assertEqual(response_a.status_code, 201)
        self.assertEqual(response_b.status_code, 201)

        list_response = self.client.get("/workflows")
        self.assertEqual(list_response.status_code, 200)
        payload = list_response.json()
        self.assertIn("items", payload)
        self.assertGreaterEqual(len(payload["items"]), 2)
        item = payload["items"][0]
        self.assertIn("workflow_id", item)
        self.assertIn("name", item)
        self.assertNotIn("draft", item)

    def test_update_workflow_meta(self):
        workflow_id, _ = self._create_workflow()
        response = self.client.patch(
            f"/workflows/{workflow_id}",
            json={"name": "Renamed workflow", "description": "Updated description"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["name"], "Renamed workflow")
        self.assertEqual(payload["description"], "Updated description")

    def test_update_workflow_draft_accepts_raw_draft_payload(self):
        workflow_id, _ = self._create_workflow()
        draft = {
            "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}],
            "edges": [{"source": "start", "target": "end"}],
            "variables_schema": {"type": "object"},
        }
        response = self.client.put(f"/workflows/{workflow_id}/draft", json=draft)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["draft"]["variables_schema"], {"type": "object"})

    def test_cancel_interrupt_returns_interrupt_payload(self):
        draft = {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "ask", "type": "interaction", "config": {"prompt": "Need input"}},
                {"id": "end", "type": "end"},
            ],
            "edges": [{"source": "start", "target": "ask"}, {"source": "ask", "target": "end"}],
            "variables_schema": {},
        }
        workflow = self.client.post("/workflows", json={"name": "Interrupt workflow", "draft": draft})
        self.assertEqual(workflow.status_code, 201)
        workflow_id = workflow.json()["workflow_id"]
        self.client.post(f"/workflows/{workflow_id}/publish")

        run_response = self.client.post(f"/workflows/{workflow_id}/runs", json={"inputs": {}})
        self.assertEqual(run_response.status_code, 201)
        run_id = run_response.json()["run_id"]

        run = self.client.app.state.api_context.run_store.get(run_id)
        interrupt_id = next(iter(run.interrupts))

        cancel_response = self.client.post(f"/runs/{run_id}/interrupts/{interrupt_id}/cancel")
        self.assertEqual(cancel_response.status_code, 200)
        payload = cancel_response.json()
        self.assertEqual(payload["interrupt_id"], interrupt_id)
        self.assertEqual(payload["status"], "CANCELLED")

    def test_error_envelope_contains_correlation_id(self):
        response = self.client.get("/workflows/missing")
        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertIn("correlation_id", payload)
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")

    def test_openapi_and_reference_endpoints(self):
        openapi_response = self.client.get("/openapi.yaml")
        self.assertEqual(openapi_response.status_code, 200)
        self.assertIn("openapi: 3.0.3", openapi_response.text)

        reference_response = self.client.get("/api-reference")
        self.assertEqual(reference_response.status_code, 200)
        self.assertIn("WorkCore API Reference", reference_response.text)

    def test_agent_integration_kit_endpoints(self):
        markdown_response = self.client.get("/agent-integration-kit")
        self.assertEqual(markdown_response.status_code, 200)
        self.assertIn("WorkCore Agent Integration Kit", markdown_response.text)
        self.assertIn("/openapi.yaml", markdown_response.text)

        json_response = self.client.get("/agent-integration-kit.json")
        self.assertEqual(json_response.status_code, 200)
        payload = json_response.json()
        self.assertEqual(payload["title"], "WorkCore Agent Integration Kit")
        self.assertIn("urls", payload)
        self.assertIn("schemas", payload)
        self.assertEqual(
            payload["schemas"]["workflow_export_v1"]["properties"]["schema_version"]["const"],
            "workflow_export_v1",
        )

        guide_response = self.client.get("/workflow-authoring-guide")
        self.assertEqual(guide_response.status_code, 200)
        self.assertIn("Workflow Authoring Guide for Agents", guide_response.text)

        draft_schema_response = self.client.get("/schemas/workflow-draft.schema.json")
        self.assertEqual(draft_schema_response.status_code, 200)
        self.assertEqual(draft_schema_response.json()["title"], "WorkCore Workflow Draft")

        export_schema_response = self.client.get("/schemas/workflow-export-v1.schema.json")
        self.assertEqual(export_schema_response.status_code, 200)
        self.assertEqual(export_schema_response.json()["title"], "WorkCore Workflow Export v1")

        integration_test_ui = self.client.get("/agent-integration-test")
        self.assertEqual(integration_test_ui.status_code, 200)
        self.assertIn("WorkCore Agent Integration Test", integration_test_ui.text)

        integration_test_json = self.client.get("/agent-integration-test.json")
        self.assertEqual(integration_test_json.status_code, 200)
        report = integration_test_json.json()
        self.assertEqual(report["summary"]["status"], "PASS")
        self.assertGreater(report["summary"]["total"], 0)

        valid_draft_response = self.client.post(
            "/agent-integration-test/validate-draft",
            json={
                "draft": {
                    "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}],
                    "edges": [{"source": "start", "target": "end"}],
                    "variables_schema": {},
                }
            },
        )
        self.assertEqual(valid_draft_response.status_code, 200)
        self.assertTrue(valid_draft_response.json()["valid"])

        invalid_draft_response = self.client.post(
            "/agent-integration-test/validate-draft",
            json={"draft": {"nodes": [{"id": "start", "type": "start"}], "edges": []}},
        )
        self.assertEqual(invalid_draft_response.status_code, 200)
        self.assertFalse(invalid_draft_response.json()["valid"])
        self.assertGreater(len(invalid_draft_response.json()["errors"]), 0)

    def test_delete_workflow(self):
        workflow_id, _ = self._create_workflow()
        delete_response = self.client.delete(f"/workflows/{workflow_id}")
        self.assertEqual(delete_response.status_code, 204)

        get_response = self.client.get(f"/workflows/{workflow_id}")
        self.assertEqual(get_response.status_code, 404)

    def test_tenant_isolation_for_workflows_and_runs(self):
        headers_a = {"X-Tenant-Id": "tenant_a"}
        headers_b = {"X-Tenant-Id": "tenant_b"}
        workflow_id, _ = self._create_workflow(headers=headers_a)

        own_workflow = self.client.get(f"/workflows/{workflow_id}", headers=headers_a)
        self.assertEqual(own_workflow.status_code, 200)
        foreign_workflow = self.client.get(f"/workflows/{workflow_id}", headers=headers_b)
        self.assertEqual(foreign_workflow.status_code, 404)

        start_response = self.client.post(f"/workflows/{workflow_id}/runs", json={"inputs": {}}, headers=headers_a)
        self.assertEqual(start_response.status_code, 201)
        run_id = start_response.json()["run_id"]

        own_run = self.client.get(f"/runs/{run_id}", headers=headers_a)
        self.assertEqual(own_run.status_code, 200)
        foreign_run = self.client.get(f"/runs/{run_id}", headers=headers_b)
        self.assertEqual(foreign_run.status_code, 404)

        list_a = self.client.get("/runs", headers=headers_a)
        self.assertEqual(list_a.status_code, 200)
        self.assertEqual(len(list_a.json()["items"]), 1)

        list_b = self.client.get("/runs", headers=headers_b)
        self.assertEqual(list_b.status_code, 200)
        self.assertEqual(len(list_b.json()["items"]), 0)

        stream_foreign = self.client.get(f"/runs/{run_id}/stream", headers=headers_b)
        self.assertEqual(stream_foreign.status_code, 404)


class ApiAuthTests(unittest.TestCase):
    def setUp(self):
        self._previous_token = os.environ.get("WORKCORE_API_AUTH_TOKEN")
        os.environ["WORKCORE_API_AUTH_TOKEN"] = "test_api_token"
        self.workflow_store = InMemoryWorkflowStore()
        self.client = TestClient(create_app(workflow_store=self.workflow_store))

    def tearDown(self):
        if self._previous_token is None:
            os.environ.pop("WORKCORE_API_AUTH_TOKEN", None)
        else:
            os.environ["WORKCORE_API_AUTH_TOKEN"] = self._previous_token

    def test_auth_required_for_api_routes(self):
        draft = {
            "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}],
            "edges": [{"source": "start", "target": "end"}],
            "variables_schema": {},
        }
        unauthorized = self.client.post("/workflows", json={"name": "blocked", "draft": draft})
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(unauthorized.json()["error"]["code"], "UNAUTHORIZED")

        authorized = self.client.post(
            "/workflows",
            json={"name": "allowed", "draft": draft},
            headers={"Authorization": "Bearer test_api_token"},
        )
        self.assertEqual(authorized.status_code, 201)

    def test_health_does_not_require_auth(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_inbound_webhook_does_not_require_bearer_auth(self):
        response = self.client.post("/webhooks/inbound/test_key", json={"action": "start_run"})
        self.assertEqual(response.status_code, 404)

    def test_openapi_and_reference_do_not_require_auth(self):
        openapi_response = self.client.get("/openapi.yaml")
        self.assertEqual(openapi_response.status_code, 200)

        reference_response = self.client.get("/api-reference")
        self.assertEqual(reference_response.status_code, 200)

        kit_response = self.client.get("/agent-integration-kit")
        self.assertEqual(kit_response.status_code, 200)

        kit_json_response = self.client.get("/agent-integration-kit.json")
        self.assertEqual(kit_json_response.status_code, 200)

        integration_test_response = self.client.get("/agent-integration-test")
        self.assertEqual(integration_test_response.status_code, 200)

        integration_test_json_response = self.client.get("/agent-integration-test.json")
        self.assertEqual(integration_test_json_response.status_code, 200)

        schema_response = self.client.get("/schemas/workflow-draft.schema.json")
        self.assertEqual(schema_response.status_code, 200)

        validate_response = self.client.post(
            "/agent-integration-test/validate-draft",
            json={
                "draft": {
                    "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}],
                    "edges": [{"source": "start", "target": "end"}],
                }
            },
        )
        self.assertEqual(validate_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
