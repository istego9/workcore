import asyncio
import json
import os
import unittest
from pathlib import Path

from starlette.testclient import TestClient

from apps.orchestrator.api import create_app
from apps.orchestrator.api.artifact_store import InMemoryArtifactStore
from apps.orchestrator.api.workflow_store import InMemoryWorkflowStore
from apps.orchestrator.llm_adapter import ResponsesLLMRouter

_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "routing_eval" / "baseline.json"


class RoutingHarnessTests(unittest.TestCase):
    def setUp(self):
        self._previous_api_token = os.environ.get("WORKCORE_API_AUTH_TOKEN")
        os.environ.pop("WORKCORE_API_AUTH_TOKEN", None)
        self.workflow_store = InMemoryWorkflowStore()
        self.artifact_store = InMemoryArtifactStore()
        self.client = TestClient(create_app(workflow_store=self.workflow_store, artifact_store=self.artifact_store))

    def tearDown(self):
        if self._previous_api_token is None:
            os.environ.pop("WORKCORE_API_AUTH_TOKEN", None)
        else:
            os.environ["WORKCORE_API_AUTH_TOKEN"] = self._previous_api_token

    @staticmethod
    def _interaction_draft() -> dict:
        return {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "ask", "type": "interaction", "config": {"prompt": "Need input"}},
                {"id": "end", "type": "end"},
            ],
            "edges": [
                {"source": "start", "target": "ask"},
                {"source": "ask", "target": "end"},
            ],
            "variables_schema": {},
        }

    def _with_project(self, project_id: str) -> dict:
        return {"X-Project-Id": project_id}

    def _create_interaction_workflow(self, project_id: str, name: str) -> str:
        response = self.client.post(
            "/workflows",
            json={"name": name, "draft": self._interaction_draft()},
            headers=self._with_project(project_id),
        )
        self.assertEqual(response.status_code, 201)
        workflow_id = response.json()["workflow_id"]
        publish = self.client.post(
            f"/workflows/{workflow_id}/publish",
            headers=self._with_project(project_id),
        )
        self.assertEqual(publish.status_code, 200)
        return workflow_id

    def _bootstrap_project(
        self,
        project_id: str,
        workflow_defs: list[dict],
        routing_policy: dict,
        orchestrator_id: str = "orc_default",
    ) -> None:
        self.client.get("/health")
        ctx = self.client.app.state.api_context

        async def _setup() -> None:
            await ctx.ensure_orchestration()
            store = ctx.orchestration_store
            await store.upsert_project(
                project_id=project_id,
                tenant_id="local",
                project_name="Routing Harness",
                default_orchestrator_id=orchestrator_id,
                settings={"orchestrator_enabled": True},
            )
            await store.upsert_orchestrator_config(
                project_id=project_id,
                orchestrator_id=orchestrator_id,
                name="Routing Harness",
                tenant_id="local",
                routing_policy=routing_policy,
                fallback_workflow_id=None,
                prompt_profile="default",
                set_as_default=True,
            )
            for definition in workflow_defs:
                await store.upsert_workflow_definition(
                    project_id=project_id,
                    workflow_id=definition["workflow_id"],
                    tenant_id="local",
                    name=definition["name"],
                    description=definition["description"],
                    tags=definition.get("tags") or [],
                    examples=definition.get("examples") or [],
                    active=True,
                    is_fallback=bool(definition.get("is_fallback")),
                )

        asyncio.run(_setup())

    def _set_heuristic_router(self) -> None:
        self.client.get("/health")
        ctx = self.client.app.state.api_context

        async def _set_router() -> None:
            await ctx.ensure_orchestration()
            ctx.project_orchestrator.llm_router = ResponsesLLMRouter(force_heuristic=True)

        asyncio.run(_set_router())

    def test_routing_harness_baseline_fixture(self):
        fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        project_id = str(fixture["project_id"])

        workflow_ids_by_key: dict[str, str] = {}
        workflow_defs: list[dict] = []
        for workflow in fixture["workflows"]:
            workflow_key = str(workflow["key"])
            workflow_id = self._create_interaction_workflow(project_id, str(workflow["name"]))
            workflow_ids_by_key[workflow_key] = workflow_id
            workflow_defs.append(
                {
                    "workflow_id": workflow_id,
                    "name": workflow["name"],
                    "description": workflow["description"],
                    "tags": list(workflow.get("tags") or []),
                    "examples": list(workflow.get("examples") or []),
                    "is_fallback": bool(workflow.get("is_fallback")),
                }
            )

        self._bootstrap_project(
            project_id=project_id,
            workflow_defs=workflow_defs,
            routing_policy=dict(fixture["routing_policy"]),
        )
        self._set_heuristic_router()

        replay_cases = []
        for case in fixture["cases"]:
            replay_case = {
                "case_id": case["case_id"],
                "message_text": case["message_text"],
                "expected_action": case["expected_action"],
            }
            expected_key = case.get("expected_workflow_key")
            if expected_key:
                replay_case["expected_workflow_id"] = workflow_ids_by_key[str(expected_key)]
            replay_cases.append(replay_case)

        response = self.client.post(
            "/orchestrator/eval/replay",
            json={
                "project_id": project_id,
                "session_id": fixture["session_id"],
                "user_id": fixture["user_id"],
                "cases": replay_cases,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        metrics = payload.get("metrics") or {}
        thresholds = fixture.get("thresholds") or {}

        self.assertGreaterEqual(
            float(metrics.get("action_accuracy") or 0.0),
            float(thresholds.get("action_accuracy_min") or 0.0),
        )
        self.assertGreaterEqual(
            float(metrics.get("workflow_accuracy") or 0.0),
            float(thresholds.get("workflow_accuracy_min") or 0.0),
        )
        self.assertGreaterEqual(
            float(metrics.get("exact_match_rate") or 0.0),
            float(thresholds.get("exact_match_rate_min") or 0.0),
        )

        items = payload.get("items") or []
        self.assertEqual(len(items), len(replay_cases))
        mismatches = [item for item in items if item.get("matched_exact") is False]
        self.assertFalse(mismatches)


if __name__ == "__main__":
    unittest.main()
