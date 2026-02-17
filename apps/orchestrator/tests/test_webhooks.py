import json
import time
import unittest

from starlette.testclient import TestClient

from apps.orchestrator.api import create_app
from apps.orchestrator.api.workflow_store import InMemoryWorkflowStore
from apps.orchestrator.webhooks.signing import sign_payload


class WebhooksTests(unittest.TestCase):
    def setUp(self):
        self.workflow_store = InMemoryWorkflowStore()
        self.project_headers = {"X-Project-Id": "proj_webhooks"}
        self.client = TestClient(
            create_app(
                workflow_store=self.workflow_store,
                default_inbound_secret="secret_default",
            )
        )

        draft = {
            "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}],
            "edges": [{"source": "start", "target": "end"}],
            "variables_schema": {},
        }
        response = self.client.post(
            "/workflows",
            json={"name": "Webhook workflow", "draft": draft},
            headers=self.project_headers,
        )
        workflow_id = response.json()["workflow_id"]
        publish_response = self.client.post(f"/workflows/{workflow_id}/publish", headers=self.project_headers)
        self.workflow_id = publish_response.json()["workflow_id"]

    def test_inbound_webhook_start_run(self):
        payload = {"action": "start_run", "workflow_id": self.workflow_id, "inputs": {}}
        body = json.dumps(payload).encode("utf-8")
        ts = str(int(time.time()))
        signature = sign_payload("secret_default", ts, body)

        response = self.client.post(
            "/webhooks/inbound/default",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Timestamp": ts,
                "X-Webhook-Signature": signature,
            },
        )
        self.assertEqual(response.status_code, 202)
        self.assertIn("run_id", response.json())

    def test_inbound_webhook_rejects_invalid_signature(self):
        payload = {"action": "start_run", "workflow_id": self.workflow_id, "inputs": {}}
        body = json.dumps(payload).encode("utf-8")
        ts = str(int(time.time()))
        bad_signature = sign_payload("wrong_secret", ts, body)

        response = self.client.post(
            "/webhooks/inbound/default",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Timestamp": ts,
                "X-Webhook-Signature": bad_signature,
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "UNAUTHORIZED")

    def test_outbound_registration(self):
        response = self.client.post(
            "/webhooks/outbound",
            json={"url": "https://example.com/hook", "event_types": ["run_completed"]},
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("subscription_id", data)
        self.assertNotIn("secret", data)


if __name__ == "__main__":
    unittest.main()
