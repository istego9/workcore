import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from starlette.testclient import TestClient

from apps.orchestrator.api import create_app
from apps.orchestrator.api.app import validate_runtime_security_env
from apps.orchestrator.api.artifact_store import InMemoryArtifactStore
from apps.orchestrator.api.workflow_store import InMemoryWorkflowStore
from apps.orchestrator.streaming.sse import _event_stream


def _run_ledger_fk_error_text(run_id: str) -> str:
    return (
        'insert or update on table "run_ledger" violates foreign key constraint '
        f'"run_ledger_run_id_fkey"\nDETAIL:  Key (run_id)=({run_id}) is not present in table "runs".'
    )


class GuardRunVisibilityLedgerStore:
    def __init__(self, run_store):
        self.run_store = run_store
        self.calls = 0
        self.entries = []

    async def append_entries(self, entries):
        self.calls += 1
        for entry in entries:
            tenant = getattr(entry, "tenant_id", "local")
            loaded = self.run_store.get(entry.run_id, tenant_id=tenant)
            if asyncio.iscoroutine(loaded):
                loaded = await loaded
            if loaded is None:
                raise RuntimeError(_run_ledger_fk_error_text(entry.run_id))
        self.entries.extend(entries)

    async def list_run(self, run_id: str, tenant_id: str | None = None, limit: int = 200):
        resolved_tenant = tenant_id or "local"
        items = [
            item
            for item in self.entries
            if getattr(item, "run_id", "") == run_id and getattr(item, "tenant_id", "local") == resolved_tenant
        ]
        return items[:limit]

    async def close(self) -> None:
        return None


class FlakyFkLedgerStore:
    def __init__(self, failures_before_success: int):
        self.failures_before_success = failures_before_success
        self.calls = 0
        self.entries = []

    async def append_entries(self, entries):
        self.calls += 1
        if self.calls <= self.failures_before_success:
            run_id = entries[0].run_id if entries else "run_unknown"
            raise RuntimeError(_run_ledger_fk_error_text(run_id))
        self.entries.extend(entries)

    async def list_run(self, run_id: str, tenant_id: str | None = None, limit: int = 200):
        resolved_tenant = tenant_id or "local"
        items = [
            item
            for item in self.entries
            if getattr(item, "run_id", "") == run_id and getattr(item, "tenant_id", "local") == resolved_tenant
        ]
        return items[:limit]

    async def close(self) -> None:
        return None


class AlwaysFailFkLedgerStore:
    def __init__(self):
        self.calls = 0

    async def append_entries(self, entries):
        self.calls += 1
        run_id = entries[0].run_id if entries else "run_unknown"
        raise RuntimeError(_run_ledger_fk_error_text(run_id))

    async def list_run(self, run_id: str, tenant_id: str | None = None, limit: int = 200):
        return []

    async def close(self) -> None:
        return None


class ApiTests(unittest.TestCase):
    def setUp(self):
        self._previous_api_token = os.environ.get("WORKCORE_API_AUTH_TOKEN")
        os.environ.pop("WORKCORE_API_AUTH_TOKEN", None)
        self.workflow_store = InMemoryWorkflowStore()
        self.artifact_store = InMemoryArtifactStore()
        self.default_project_id = "proj_test"
        self.client = TestClient(create_app(workflow_store=self.workflow_store, artifact_store=self.artifact_store))

    def tearDown(self):
        if self._previous_api_token is None:
            os.environ.pop("WORKCORE_API_AUTH_TOKEN", None)
        else:
            os.environ["WORKCORE_API_AUTH_TOKEN"] = self._previous_api_token

    def _with_project(self, headers=None, project_id: str | None = None):
        merged = dict(headers or {})
        merged.setdefault("X-Project-Id", project_id or self.default_project_id)
        return merged

    def _create_workflow(self, headers=None):
        headers = self._with_project(headers)
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

    def _create_interaction_workflow(self, headers=None):
        headers = self._with_project(headers)
        draft = {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "ask", "type": "interaction", "config": {"prompt": "Need input"}},
                {"id": "end", "type": "end"},
            ],
            "edges": [{"source": "start", "target": "ask"}, {"source": "ask", "target": "end"}],
            "variables_schema": {},
        }
        response = self.client.post("/workflows", json={"name": "Interaction workflow", "draft": draft}, headers=headers)
        self.assertEqual(response.status_code, 201)
        workflow_id = response.json()["workflow_id"]
        publish_response = self.client.post(f"/workflows/{workflow_id}/publish", headers=headers)
        self.assertEqual(publish_response.status_code, 200)
        version_id = publish_response.json()["version_id"]
        return workflow_id, version_id

    def _create_output_workflow(self, headers=None):
        headers = self._with_project(headers)
        draft = {
            "nodes": [
                {"id": "start", "type": "start"},
                {
                    "id": "out",
                    "type": "output",
                    "config": {"value": {"result": {"claim_id": "clm_1", "decision": "approve", "raw": "x"}}},
                },
                {"id": "end", "type": "end"},
            ],
            "edges": [{"source": "start", "target": "out"}, {"source": "out", "target": "end"}],
            "variables_schema": {},
        }
        response = self.client.post("/workflows", json={"name": "Output workflow", "draft": draft}, headers=headers)
        self.assertEqual(response.status_code, 201)
        workflow_id = response.json()["workflow_id"]
        publish_response = self.client.post(f"/workflows/{workflow_id}/publish", headers=headers)
        self.assertEqual(publish_response.status_code, 200)
        version_id = publish_response.json()["version_id"]
        return workflow_id, version_id

    def _bootstrap_project(
        self,
        project_id: str,
        workflow_defs: list[dict],
        orchestrator_id: str = "orc_default",
        routing_policy: dict | None = None,
        fallback_workflow_id: str | None = None,
    ) -> None:
        self.client.get("/health")
        ctx = self.client.app.state.api_context

        async def _setup():
            await ctx.ensure_orchestration()
            store = ctx.orchestration_store
            await store.upsert_project(
                project_id=project_id,
                tenant_id="local",
                project_name="Test Project",
                default_orchestrator_id=orchestrator_id,
                settings={"orchestrator_enabled": True},
            )
            await store.upsert_orchestrator_config(
                project_id=project_id,
                orchestrator_id=orchestrator_id,
                name="Default orchestrator",
                tenant_id="local",
                routing_policy=routing_policy or {
                    "confidence_threshold": 0.6,
                    "switch_margin": 0.2,
                    "max_disambiguation_turns": 2,
                    "top_k_candidates": 10,
                },
                fallback_workflow_id=fallback_workflow_id,
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

    def test_create_project(self):
        response = self.client.post(
            "/projects",
            json={
                "project_id": "proj_new",
                "project_name": "New Project",
                "settings": {"orchestrator_enabled": True},
            },
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["project_id"], "proj_new")
        self.assertEqual(payload["project_name"], "New Project")
        self.assertEqual(payload["tenant_id"], "local")
        self.assertEqual(payload["settings"], {"orchestrator_enabled": True})
        self.assertIsNone(payload["default_orchestrator_id"])
        self.assertTrue(payload.get("created_at"))
        self.assertTrue(payload.get("updated_at"))

    def test_create_project_validates_payload(self):
        non_object = self.client.post("/projects", json=["bad"])
        self.assertEqual(non_object.status_code, 400)
        self.assertEqual(non_object.json()["error"]["code"], "INVALID_ARGUMENT")

        missing_id = self.client.post("/projects", json={"settings": {}})
        self.assertEqual(missing_id.status_code, 400)
        self.assertEqual(missing_id.json()["error"]["code"], "INVALID_ARGUMENT")

        missing_name = self.client.post("/projects", json={"project_id": "proj_missing_name"})
        self.assertEqual(missing_name.status_code, 400)
        self.assertEqual(missing_name.json()["error"]["code"], "INVALID_ARGUMENT")

        bad_settings = self.client.post(
            "/projects",
            json={"project_id": "proj_bad_settings", "project_name": "Bad Settings", "settings": "bad"},
        )
        self.assertEqual(bad_settings.status_code, 400)
        self.assertEqual(bad_settings.json()["error"]["code"], "INVALID_ARGUMENT")

    def test_create_project_returns_conflict_when_duplicate(self):
        first = self.client.post("/projects", json={"project_id": "proj_dup", "project_name": "Dup Project"})
        self.assertEqual(first.status_code, 201)
        second = self.client.post("/projects", json={"project_id": "proj_dup", "project_name": "Dup Project"})
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["error"]["code"], "CONFLICT")

    def test_list_projects(self):
        self.client.post("/projects", json={"project_id": "proj_list_a", "project_name": "List A"})
        self.client.post("/projects", json={"project_id": "proj_list_b", "project_name": "List B"})
        self.client.post("/projects", json={"project_id": "proj_list_c", "project_name": "List C"})

        response = self.client.get("/projects", params={"limit": 2})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["next_cursor"], None)
        self.assertEqual(len(payload["items"]), 2)
        self.assertEqual(payload["items"][0]["project_id"], "proj_list_c")
        self.assertEqual(payload["items"][0]["project_name"], "List C")
        self.assertEqual(payload["items"][1]["project_id"], "proj_list_b")
        self.assertEqual(payload["items"][1]["project_name"], "List B")

    def test_list_projects_is_tenant_scoped(self):
        self.client.post(
            "/projects",
            json={"project_id": "proj_local_only", "project_name": "Local Only"},
            headers={"X-Tenant-Id": "tenant_local"},
        )
        self.client.post(
            "/projects",
            json={"project_id": "proj_other_only", "project_name": "Other Only"},
            headers={"X-Tenant-Id": "tenant_other"},
        )

        local_response = self.client.get("/projects", headers={"X-Tenant-Id": "tenant_local"})
        self.assertEqual(local_response.status_code, 200)
        self.assertEqual([item["project_id"] for item in local_response.json()["items"]], ["proj_local_only"])

        other_response = self.client.get("/projects", headers={"X-Tenant-Id": "tenant_other"})
        self.assertEqual(other_response.status_code, 200)
        self.assertEqual([item["project_id"] for item in other_response.json()["items"]], ["proj_other_only"])

    def test_list_projects_validates_limit(self):
        response = self.client.get("/projects", params={"limit": "not_an_int"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_ARGUMENT")

    def test_update_project(self):
        project_id = "proj_update_me"
        create_response = self.client.post(
            "/projects",
            json={"project_id": project_id, "project_name": "Before Name"},
        )
        self.assertEqual(create_response.status_code, 201)

        response = self.client.patch(
            f"/projects/{project_id}",
            json={"project_name": "After Name"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["project_id"], project_id)
        self.assertEqual(payload["project_name"], "After Name")
        self.assertEqual(payload["tenant_id"], "local")

    def test_update_project_validates_payload_and_scope(self):
        missing_name = self.client.patch("/projects/proj_any", json={})
        self.assertEqual(missing_name.status_code, 400)
        self.assertEqual(missing_name.json()["error"]["code"], "INVALID_ARGUMENT")

        not_found = self.client.patch("/projects/proj_missing", json={"project_name": "Updated"})
        self.assertEqual(not_found.status_code, 404)
        self.assertEqual(not_found.json()["error"]["code"], "ERR_PROJECT_NOT_FOUND")

    def test_delete_project(self):
        project_id = "proj_delete_me"
        create_response = self.client.post(
            "/projects",
            json={"project_id": project_id, "project_name": "Delete Me"},
        )
        self.assertEqual(create_response.status_code, 201)

        delete_response = self.client.delete(f"/projects/{project_id}")
        self.assertEqual(delete_response.status_code, 204)
        self.assertEqual(delete_response.text, "")

        list_response = self.client.get("/projects")
        self.assertEqual(list_response.status_code, 200)
        project_ids = [item["project_id"] for item in list_response.json()["items"]]
        self.assertNotIn(project_id, project_ids)

    def test_delete_project_requires_empty_scope(self):
        project_id = "proj_delete_blocked"
        create_project_response = self.client.post(
            "/projects",
            json={"project_id": project_id, "project_name": "Delete Blocked"},
        )
        self.assertEqual(create_project_response.status_code, 201)

        headers = self._with_project(project_id=project_id)
        workflow_id, _ = self._create_workflow(headers=headers)
        self.assertTrue(workflow_id.startswith("wf_"))

        delete_response = self.client.delete(f"/projects/{project_id}")
        self.assertEqual(delete_response.status_code, 409)
        self.assertEqual(delete_response.json()["error"]["code"], "ERR_PROJECT_NOT_EMPTY")

    def test_delete_project_returns_not_found_when_missing(self):
        response = self.client.delete("/projects/proj_missing")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "ERR_PROJECT_NOT_FOUND")

    def test_upsert_project_workflow_definition_enables_direct_orchestrator_mode(self):
        project_id = "proj_registry_direct"
        workflow_headers = self._with_project(project_id=project_id)
        workflow_id, _ = self._create_workflow(headers=workflow_headers)

        project_response = self.client.post(
            "/projects",
            json={
                "project_id": project_id,
                "project_name": "Registry Direct",
                "settings": {"orchestrator_enabled": True},
            },
        )
        self.assertEqual(project_response.status_code, 201)

        definition_response = self.client.post(
            f"/projects/{project_id}/workflow-definitions",
            json={
                "workflow_id": workflow_id,
                "name": "Direct registry flow",
                "description": "Public registry bootstrap",
                "tags": ["direct"],
                "examples": ["start direct"],
                "active": True,
                "is_fallback": False,
            },
        )
        self.assertEqual(definition_response.status_code, 201)
        definition_payload = definition_response.json()
        self.assertEqual(definition_payload["project_id"], project_id)
        self.assertEqual(definition_payload["workflow_id"], workflow_id)
        self.assertEqual(definition_payload["name"], "Direct registry flow")

        message_response = self.client.post(
            "/orchestrator/messages",
            json={
                "session_id": "s_registry_direct",
                "user_id": "u_registry_direct",
                "project_id": project_id,
                "workflow_id": workflow_id,
                "message": {"id": "m_registry_direct_1", "text": "start"},
            },
        )
        self.assertEqual(message_response.status_code, 200)
        payload = message_response.json()
        self.assertEqual(payload["mode"], "direct")
        self.assertEqual(payload["chosen_workflow_id"], workflow_id)
        self.assertIn(payload["chosen_action"], {"START_WORKFLOW", "RESUME_CURRENT"})
        trace = payload.get("decision_trace") or {}
        self.assertEqual(trace.get("mode"), "direct")
        self.assertEqual(trace.get("selected_workflow_id"), workflow_id)
        self.assertEqual(trace.get("selected_action"), payload["chosen_action"])
        self.assertTrue(isinstance(trace.get("candidates"), list) and trace["candidates"])

    def test_upsert_project_workflow_definition_validates_scope(self):
        project_id = "proj_registry_scope"
        self.client.post(
            "/projects",
            json={
                "project_id": project_id,
                "project_name": "Registry Scope",
                "settings": {"orchestrator_enabled": True},
            },
        )

        missing_project_response = self.client.post(
            "/projects/proj_missing/workflow-definitions",
            json={
                "workflow_id": "wf_missing",
                "name": "Missing project",
                "description": "No project",
            },
        )
        self.assertEqual(missing_project_response.status_code, 404)
        self.assertEqual(missing_project_response.json()["error"]["code"], "ERR_PROJECT_NOT_FOUND")

        foreign_workflow_id, _ = self._create_workflow(headers=self._with_project(project_id="proj_other"))
        foreign_workflow_response = self.client.post(
            f"/projects/{project_id}/workflow-definitions",
            json={
                "workflow_id": foreign_workflow_id,
                "name": "Foreign workflow",
                "description": "Wrong project scope",
            },
        )
        self.assertEqual(foreign_workflow_response.status_code, 409)
        self.assertEqual(foreign_workflow_response.json()["error"]["code"], "ERR_WORKFLOW_NOT_IN_PROJECT")

    def test_upsert_project_orchestrator_sets_default(self):
        project_id = "proj_registry_orc"
        workflow_headers = self._with_project(project_id=project_id)
        workflow_id, _ = self._create_workflow(headers=workflow_headers)

        project_response = self.client.post(
            "/projects",
            json={
                "project_id": project_id,
                "project_name": "Registry Orchestrator",
                "settings": {"orchestrator_enabled": True},
            },
        )
        self.assertEqual(project_response.status_code, 201)

        config_response = self.client.post(
            f"/projects/{project_id}/orchestrators",
            json={
                "orchestrator_id": "orc_default",
                "name": "Default orchestrator",
                "routing_policy": {
                    "confidence_threshold": 0.6,
                    "switch_margin": 0.2,
                    "max_disambiguation_turns": 2,
                    "top_k_candidates": 10,
                },
                "fallback_workflow_id": workflow_id,
                "prompt_profile": "default",
                "set_as_default": True,
            },
        )
        self.assertEqual(config_response.status_code, 201)
        config_payload = config_response.json()
        self.assertEqual(config_payload["project_id"], project_id)
        self.assertEqual(config_payload["orchestrator_id"], "orc_default")
        self.assertEqual(config_payload["fallback_workflow_id"], workflow_id)

        self.client.get("/health")
        ctx = self.client.app.state.api_context

        async def _load_project():
            await ctx.ensure_orchestration()
            return await ctx.orchestration_store.get_project(project_id, tenant_id="local")

        project = asyncio.run(_load_project())
        self.assertIsNotNone(project)
        self.assertEqual(project.default_orchestrator_id, "orc_default")

    def test_orchestrator_message_requires_project_id(self):
        response = self.client.post(
            "/orchestrator/messages",
            json={
                "session_id": "s_1",
                "user_id": "u_1",
                "message": {"id": "m_1", "text": "hello"},
                "metadata": {},
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "ERR_PROJECT_ID_REQUIRED")

    def test_orchestrator_direct_mode_starts_workflow(self):
        workflow_id, _ = self._create_workflow()
        self._bootstrap_project(
            project_id="proj_direct",
            workflow_defs=[
                {
                    "workflow_id": workflow_id,
                    "name": "Direct flow",
                    "description": "Direct start",
                    "tags": ["direct"],
                    "examples": ["start direct"],
                }
            ],
        )
        response = self.client.post(
            "/orchestrator/messages",
            json={
                "session_id": "s_direct",
                "user_id": "u_direct",
                "project_id": "proj_direct",
                "workflow_id": workflow_id,
                "message": {"id": "m_direct_1", "text": "start"},
                "metadata": {"locale": "ru-RU"},
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "direct")
        self.assertEqual(payload["chosen_workflow_id"], workflow_id)
        self.assertIn(payload["chosen_action"], {"START_WORKFLOW", "RESUME_CURRENT"})
        trace = payload.get("decision_trace") or {}
        self.assertEqual(trace.get("mode"), "direct")
        self.assertEqual(trace.get("selected_workflow_id"), workflow_id)
        self.assertEqual(trace.get("selected_action"), payload["chosen_action"])
        self.assertIn("selection_reason", trace)
        self.assertTrue(payload.get("run_id"))

        run_response = self.client.get(f"/runs/{payload['run_id']}")
        self.assertEqual(run_response.status_code, 200)
        run_payload = run_response.json()
        metadata = run_payload.get("metadata") or {}
        self.assertEqual(metadata.get("agent_executor_mode"), "live")
        self.assertEqual(metadata.get("agent_mock"), False)
        self.assertEqual(metadata.get("llm_enabled"), True)

    def test_orchestrator_mode_disambiguates_on_low_confidence(self):
        wf_a, _ = self._create_workflow()
        wf_b, _ = self._create_workflow()
        self._bootstrap_project(
            project_id="proj_disambiguate",
            workflow_defs=[
                {
                    "workflow_id": wf_a,
                    "name": "Card workflow",
                    "description": "Credit card application",
                    "tags": ["credit", "card"],
                    "examples": ["open card"],
                },
                {
                    "workflow_id": wf_b,
                    "name": "Loan workflow",
                    "description": "Loan application",
                    "tags": ["loan"],
                    "examples": ["apply loan"],
                },
            ],
            routing_policy={
                "confidence_threshold": 0.9,
                "switch_margin": 0.3,
                "max_disambiguation_turns": 2,
                "top_k_candidates": 10,
            },
        )
        response = self.client.post(
            "/orchestrator/messages",
            json={
                "session_id": "s_disambiguate",
                "user_id": "u_disambiguate",
                "project_id": "proj_disambiguate",
                "message": {"id": "m_disambiguate_1", "text": "просто помоги"},
                "metadata": {"locale": "ru-RU"},
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "orchestrated")
        self.assertEqual(payload["chosen_action"], "DISAMBIGUATE")
        self.assertEqual(payload["message"]["type"], "clarification")
        trace = payload.get("decision_trace") or {}
        self.assertEqual(trace.get("mode"), "orchestrated")
        self.assertEqual(trace.get("selected_action"), "DISAMBIGUATE")
        self.assertTrue(isinstance(trace.get("candidates"), list))

    def test_orchestrator_switches_active_workflow(self):
        wf_active, _ = self._create_interaction_workflow()
        wf_target, _ = self._create_workflow()
        self._bootstrap_project(
            project_id="proj_switch",
            workflow_defs=[
                {
                    "workflow_id": wf_active,
                    "name": "Active flow",
                    "description": "Currently running",
                    "tags": ["active"],
                    "examples": ["continue"],
                },
                {
                    "workflow_id": wf_target,
                    "name": "Card opening",
                    "description": "Open a card",
                    "tags": ["карта", "card"],
                    "examples": ["открыть карту"],
                },
            ],
            routing_policy={
                "confidence_threshold": 0.3,
                "switch_margin": 0.1,
                "max_disambiguation_turns": 1,
                "top_k_candidates": 10,
            },
        )
        start_active = self.client.post(
            "/orchestrator/messages",
            json={
                "session_id": "s_switch",
                "user_id": "u_switch",
                "project_id": "proj_switch",
                "workflow_id": wf_active,
                "message": {"id": "m_switch_1", "text": "start active"},
                "metadata": {"locale": "ru-RU"},
            },
        )
        self.assertEqual(start_active.status_code, 200)
        run_id = start_active.json()["run_id"]
        self.assertTrue(run_id)

        switch_response = self.client.post(
            "/orchestrator/messages",
            json={
                "session_id": "s_switch",
                "user_id": "u_switch",
                "project_id": "proj_switch",
                "message": {"id": "m_switch_2", "text": "хочу открыть карту"},
                "metadata": {"locale": "ru-RU"},
            },
        )
        self.assertEqual(switch_response.status_code, 200)
        payload = switch_response.json()
        self.assertEqual(payload["mode"], "orchestrated")
        self.assertEqual(payload["chosen_action"], "SWITCH_WORKFLOW")
        self.assertEqual(payload["chosen_workflow_id"], wf_target)
        trace = payload.get("decision_trace") or {}
        self.assertEqual(trace.get("selected_action"), "SWITCH_WORKFLOW")
        self.assertEqual(trace.get("selected_workflow_id"), wf_target)
        self.assertEqual(trace.get("switch_from_workflow_id"), wf_active)
        self.assertEqual(trace.get("switch_to_workflow_id"), wf_target)
        self.assertTrue(trace.get("switch_reason"))
        self.assertTrue(payload.get("run_id"))

    def test_orchestrator_cancel_not_allowed(self):
        wf_active, _ = self._create_interaction_workflow()
        self._bootstrap_project(
            project_id="proj_cancel_guard",
            workflow_defs=[
                {
                    "workflow_id": wf_active,
                    "name": "Guarded flow",
                    "description": "Flow with commit point",
                    "tags": ["guarded"],
                    "examples": ["start guarded"],
                }
            ],
            routing_policy={
                "confidence_threshold": 0.2,
                "switch_margin": 0.1,
                "max_disambiguation_turns": 1,
                "top_k_candidates": 10,
            },
        )
        start_active = self.client.post(
            "/orchestrator/messages",
            json={
                "session_id": "s_cancel_guard",
                "user_id": "u_cancel_guard",
                "project_id": "proj_cancel_guard",
                "workflow_id": wf_active,
                "message": {"id": "m_cancel_guard_1", "text": "start"},
                "metadata": {"locale": "ru-RU"},
            },
        )
        self.assertEqual(start_active.status_code, 200)
        active_run_id = start_active.json()["run_id"]

        run = self.client.app.state.api_context.run_store.get(active_run_id, tenant_id="local")
        run.metadata["cancellable"] = False
        run.metadata["commit_point_reached"] = True
        self.client.app.state.api_context.run_store.save(run, tenant_id="local")

        cancel_response = self.client.post(
            "/orchestrator/messages",
            json={
                "session_id": "s_cancel_guard",
                "user_id": "u_cancel_guard",
                "project_id": "proj_cancel_guard",
                "message": {"id": "m_cancel_guard_2", "text": "отмени"},
                "metadata": {"locale": "ru-RU"},
            },
        )
        self.assertEqual(cancel_response.status_code, 200)
        payload = cancel_response.json()
        self.assertEqual(payload["chosen_action"], "CANCEL")
        self.assertIn("Нельзя отменить", payload["message"]["text"])
        action_error = payload.get("action_error") or {}
        self.assertEqual(action_error.get("code"), "ERR_CANCEL_NOT_ALLOWED")
        self.assertEqual(action_error.get("category"), "action")
        self.assertFalse(action_error.get("retryable"))

    def test_orchestrator_cancel_without_active_workflow_returns_action_error(self):
        from apps.orchestrator.llm_adapter import ResponsesLLMRouter

        workflow_id, _ = self._create_workflow()
        self._bootstrap_project(
            project_id="proj_cancel_no_active",
            workflow_defs=[
                {
                    "workflow_id": workflow_id,
                    "name": "Cancel fallback flow",
                    "description": "Flow for cancel without active run",
                    "tags": ["cancel"],
                    "examples": ["start"],
                }
            ],
            routing_policy={
                "confidence_threshold": 0.2,
                "switch_margin": 0.1,
                "max_disambiguation_turns": 1,
                "top_k_candidates": 10,
            },
        )
        self.client.get("/health")
        ctx = self.client.app.state.api_context

        async def _set_heuristic_router():
            await ctx.ensure_orchestration()
            ctx.project_orchestrator.llm_router = ResponsesLLMRouter(force_heuristic=True)

        asyncio.run(_set_heuristic_router())

        response = self.client.post(
            "/orchestrator/messages",
            json={
                "session_id": "s_cancel_no_active",
                "user_id": "u_cancel_no_active",
                "project_id": "proj_cancel_no_active",
                "message": {"id": "m_cancel_no_active_1", "text": "отмени"},
                "metadata": {"locale": "ru-RU"},
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["chosen_action"], "CANCEL")
        action_error = payload.get("action_error") or {}
        self.assertEqual(action_error.get("code"), "ERR_NO_ACTIVE_WORKFLOW")
        self.assertEqual(action_error.get("category"), "action")
        self.assertTrue(action_error.get("retryable"))

    def test_orchestrator_stack_endpoint(self):
        workflow_id, _ = self._create_workflow()
        self._bootstrap_project(
            project_id="proj_stack",
            workflow_defs=[
                {
                    "workflow_id": workflow_id,
                    "name": "Stack flow",
                    "description": "Flow for stack diagnostics",
                    "tags": ["stack"],
                    "examples": ["start stack"],
                }
            ],
        )
        response = self.client.post(
            "/orchestrator/messages",
            json={
                "session_id": "s_stack",
                "user_id": "u_stack",
                "project_id": "proj_stack",
                "workflow_id": workflow_id,
                "message": {"id": "m_stack_1", "text": "start"},
                "metadata": {"locale": "ru-RU"},
            },
        )
        self.assertEqual(response.status_code, 200)

        stack_response = self.client.get("/orchestrator/sessions/s_stack/stack", params={"project_id": "proj_stack"})
        self.assertEqual(stack_response.status_code, 200)
        stack_payload = stack_response.json()
        self.assertEqual(stack_payload["project_id"], "proj_stack")
        self.assertEqual(stack_payload["session_id"], "s_stack")
        self.assertGreaterEqual(len(stack_payload["items"]), 1)

    def test_orchestrator_context_set_get_unset(self):
        set_response = self.client.post(
            "/orchestrator/context/set",
            json={
                "scope": "session",
                "scope_id": "s_ctx_1",
                "project_id": "proj_ctx",
                "values": {"profile_id": "prof_1", "tier": "gold"},
            },
        )
        self.assertEqual(set_response.status_code, 200)
        set_payload = set_response.json()
        self.assertEqual(set_payload["context"]["profile_id"], "prof_1")
        self.assertEqual(set_payload["context"]["tier"], "gold")

        get_response = self.client.post(
            "/orchestrator/context/get",
            json={
                "scope": "session",
                "scope_id": "s_ctx_1",
                "project_id": "proj_ctx",
                "keys": ["profile_id"],
            },
        )
        self.assertEqual(get_response.status_code, 200)
        get_payload = get_response.json()
        self.assertEqual(get_payload["context"], {"profile_id": "prof_1"})

        unset_response = self.client.post(
            "/orchestrator/context/unset",
            json={
                "scope": "session",
                "scope_id": "s_ctx_1",
                "project_id": "proj_ctx",
                "keys": ["tier"],
            },
        )
        self.assertEqual(unset_response.status_code, 200)
        unset_payload = unset_response.json()
        self.assertEqual(unset_payload["removed_keys"], ["tier"])
        self.assertEqual(unset_payload["context"], {"profile_id": "prof_1"})

    def test_orchestrator_direct_mode_prefills_session_context_into_inputs(self):
        project_id = "proj_ctx_prefill"
        headers = self._with_project(project_id=project_id)
        draft = {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "out", "type": "output", "config": {"expression": "inputs['context']['profile_id']"}},
                {"id": "end", "type": "end"},
            ],
            "edges": [{"source": "start", "target": "out"}, {"source": "out", "target": "end"}],
            "variables_schema": {},
        }
        workflow_create = self.client.post(
            "/workflows",
            json={"name": "Context prefill workflow", "draft": draft},
            headers=headers,
        )
        self.assertEqual(workflow_create.status_code, 201)
        workflow_id = workflow_create.json()["workflow_id"]
        workflow_publish = self.client.post(f"/workflows/{workflow_id}/publish", headers=headers)
        self.assertEqual(workflow_publish.status_code, 200)

        self._bootstrap_project(
            project_id=project_id,
            workflow_defs=[
                {
                    "workflow_id": workflow_id,
                    "name": "Context prefill workflow",
                    "description": "Uses inputs.context",
                    "tags": ["context"],
                    "examples": ["start"],
                }
            ],
        )

        set_response = self.client.post(
            "/orchestrator/context/set",
            json={
                "scope": "session",
                "scope_id": "s_ctx_prefill",
                "project_id": project_id,
                "values": {"profile_id": "prof_ctx_42"},
            },
        )
        self.assertEqual(set_response.status_code, 200)

        route_response = self.client.post(
            "/orchestrator/messages",
            json={
                "session_id": "s_ctx_prefill",
                "user_id": "u_ctx_prefill",
                "project_id": project_id,
                "workflow_id": workflow_id,
                "message": {"id": "m_ctx_prefill_1", "text": "start"},
            },
        )
        self.assertEqual(route_response.status_code, 200)
        run_id = route_response.json().get("run_id")
        self.assertTrue(run_id)

        run_response = self.client.get(f"/runs/{run_id}")
        self.assertEqual(run_response.status_code, 200)
        run_payload = run_response.json()
        self.assertEqual(run_payload.get("inputs", {}).get("context", {}).get("profile_id"), "prof_ctx_42")
        self.assertEqual(run_payload.get("outputs"), {"result": "prof_ctx_42"})

    def test_start_and_get_run(self):
        workflow_id, _ = self._create_workflow()
        response = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={"inputs": {}},
            headers=self._with_project(),
        )
        self.assertEqual(response.status_code, 201)
        created = response.json()
        run_id = created["run_id"]
        self.assertEqual(created.get("mode"), "live")
        self.assertTrue(created.get("created_at"))
        self.assertTrue(created.get("updated_at"))

        get_response = self.client.get(f"/runs/{run_id}")
        self.assertEqual(get_response.status_code, 200)
        loaded = get_response.json()
        self.assertEqual(loaded["run_id"], run_id)
        self.assertTrue(loaded.get("created_at"))
        self.assertTrue(loaded.get("updated_at"))

    def test_start_run_test_mode(self):
        workflow_id, _ = self._create_workflow()
        response = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={"inputs": {}, "mode": "test"},
            headers=self._with_project(),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json().get("mode"), "test")

    def test_start_run_live_mode_overrides_default_mock_executor(self):
        class FakeLiveExecutor:
            def __call__(self, run, node, emit):
                from apps.orchestrator.executors.types import ExecutorResult

                return ExecutorResult(output={"mock": False, "provider": "live"})

        with mock.patch.dict(os.environ, {"AGENT_EXECUTOR_MODE": "mock"}, clear=False):
            with mock.patch("apps.orchestrator.api.app.AGENTS_AVAILABLE", True):
                with mock.patch("apps.orchestrator.api.app.AgentExecutor", return_value=FakeLiveExecutor()):
                    client = TestClient(create_app(workflow_store=InMemoryWorkflowStore()))
                    headers = {"X-Project-Id": "proj_live_override"}
                    draft = {
                        "nodes": [
                            {"id": "start", "type": "start"},
                            {
                                "id": "agent",
                                "type": "agent",
                                "config": {"instructions": "Return JSON", "user_input": "estimate"},
                            },
                            {"id": "end", "type": "end"},
                        ],
                        "edges": [
                            {"source": "start", "target": "agent"},
                            {"source": "agent", "target": "end"},
                        ],
                        "variables_schema": {},
                    }

                    create_response = client.post(
                        "/workflows",
                        json={"name": "Agent workflow", "draft": draft},
                        headers=headers,
                    )
                    self.assertEqual(create_response.status_code, 201)
                    workflow_id = create_response.json()["workflow_id"]

                    publish_response = client.post(f"/workflows/{workflow_id}/publish", headers=headers)
                    self.assertEqual(publish_response.status_code, 200)

                    run_response = client.post(
                        f"/workflows/{workflow_id}/runs",
                        json={"inputs": {}, "mode": "live"},
                        headers=headers,
                    )
                    self.assertEqual(run_response.status_code, 201)
                    payload = run_response.json()
                    self.assertEqual(payload.get("metadata", {}).get("agent_executor_mode"), "live")

                    node_runs = payload.get("node_runs") or []
                    agent_run = next((item for item in node_runs if item.get("node_id") == "agent"), None)
                    self.assertIsNotNone(agent_run)
                    self.assertEqual(agent_run.get("output", {}).get("mock"), False)

    def test_start_run_exposes_transparent_metadata(self):
        headers = {
            "X-Correlation-Id": "corr_fixed",
            "X-Trace-Id": "trace_fixed",
            "X-Tenant-Id": "tenant_demo",
            "X-Project-Id": "proj_1",
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
            headers=self._with_project(headers),
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
            headers=self._with_project(),
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENT")

    def test_start_run_applies_state_and_output_projection_controls(self):
        workflow_id, _ = self._create_output_workflow()
        response = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={
                "inputs": {
                    "documents": [
                        {
                            "doc_id": "doc_1",
                            "pages": [
                                {
                                    "page_number": 1,
                                    "artifact_ref": "artf_1",
                                    "image_base64": "AAAABBBB",
                                    "text": "hello",
                                }
                            ],
                        }
                    ]
                },
                "state_exclude_paths": ["documents.pages.image_base64"],
                "output_include_paths": ["result.claim_id"],
            },
            headers=self._with_project(),
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        page = payload["state"]["documents"][0]["pages"][0]
        self.assertNotIn("image_base64", page)
        self.assertEqual(page.get("artifact_ref"), "artf_1")
        self.assertEqual(payload.get("outputs"), {"result": {"claim_id": "clm_1"}})

        get_response = self.client.get(f"/runs/{payload['run_id']}", headers=self._with_project())
        self.assertEqual(get_response.status_code, 200)
        loaded = get_response.json()
        self.assertEqual(loaded.get("outputs"), {"result": {"claim_id": "clm_1"}})
        loaded_page = loaded["state"]["documents"][0]["pages"][0]
        self.assertNotIn("image_base64", loaded_page)

    def test_start_run_validates_projection_controls(self):
        workflow_id, _ = self._create_workflow()
        bad_type = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={"inputs": {}, "state_exclude_paths": "documents"},
            headers=self._with_project(),
        )
        self.assertEqual(bad_type.status_code, 400)
        self.assertEqual(bad_type.json()["error"]["code"], "INVALID_ARGUMENT")

        bad_path = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={"inputs": {}, "output_include_paths": ["documents..image_base64"]},
            headers=self._with_project(),
        )
        self.assertEqual(bad_path.status_code, 400)
        self.assertEqual(bad_path.json()["error"]["code"], "projection.path_invalid")

    def test_start_run_applies_version_projection_defaults_for_newly_published_versions(self):
        workflow_id, _ = self._create_output_workflow()
        response = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={
                "inputs": {
                    "documents": [
                        {
                            "doc_id": "doc_1",
                            "pages": [{"page_number": 1, "artifact_ref": "artf_1", "image_base64": "AAAABBBB"}],
                        }
                    ]
                }
            },
            headers=self._with_project(),
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        page = payload["state"]["documents"][0]["pages"][0]
        self.assertNotIn("image_base64", page)
        self.assertEqual(payload.get("outputs"), {"result": {"claim_id": "clm_1", "decision": "approve", "raw": "x"}})
        metadata = payload.get("metadata", {})
        self.assertEqual(metadata.get("state_exclude_paths"), ["documents.pages.image_base64", "documents.image_base64"])

    def test_start_run_keeps_legacy_behavior_without_version_defaults(self):
        workflow_id, version_id = self._create_output_workflow()
        version = self.workflow_store.versions[version_id]
        content = dict(version.content)
        content.pop("_workcore", None)
        version.content = content

        response = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={
                "version_id": version_id,
                "inputs": {
                    "documents": [
                        {
                            "doc_id": "doc_1",
                            "pages": [{"page_number": 1, "artifact_ref": "artf_1", "image_base64": "AAAABBBB"}],
                        }
                    ]
                },
            },
            headers=self._with_project(),
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        page = payload["state"]["documents"][0]["pages"][0]
        self.assertEqual(page.get("image_base64"), "AAAABBBB")

    def test_read_artifact_returns_content(self):
        self.artifact_store.put(
            "artf_local_1",
            {"text": "payload"},
            mime_type="application/json",
            metadata={"source": "test"},
            tenant_id="local",
        )
        response = self.client.get("/artifacts/artf_local_1")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("artifact_ref"), "artf_local_1")
        self.assertEqual(payload.get("mime_type"), "application/json")
        self.assertEqual(payload.get("content"), {"text": "payload"})
        self.assertEqual(payload.get("metadata"), {"source": "test"})

    def test_read_artifact_returns_not_found_code(self):
        response = self.client.get("/artifacts/artf_missing")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "artifact.not_found")

    def test_read_artifact_returns_access_denied_code(self):
        self.artifact_store.put("artf_tenant_a", {"text": "x"}, tenant_id="tenant_a")
        response = self.client.get("/artifacts/artf_tenant_a", headers={"X-Tenant-Id": "tenant_b"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "artifact.access_denied")

    def test_read_artifact_returns_expired_code(self):
        self.artifact_store.put(
            "artf_expired",
            {"text": "x"},
            tenant_id="local",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        response = self.client.get("/artifacts/artf_expired")
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["error"]["code"], "artifact.expired")

    def test_start_run_requires_project_id(self):
        workflow_id, _ = self._create_workflow()
        response = self.client.post(f"/workflows/{workflow_id}/runs", json={"inputs": {}})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "ERR_PROJECT_ID_REQUIRED")

    def test_start_run_idempotency_key_reuses_response(self):
        workflow_id, _ = self._create_workflow()
        headers = self._with_project({"Idempotency-Key": "idem_run_1"})
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

    def test_start_run_succeeds_when_idempotency_cache_write_fails(self):
        token = os.getenv("WORKCORE_API_AUTH_TOKEN")
        auth_headers = {"Authorization": f"Bearer {token}"} if token else {}
        workflow_id, _ = self._create_workflow(headers=auth_headers)

        class FailingIdempotencyStore:
            async def get(self, key, scope, tenant_id=None):
                return None

            async def set(self, key, scope, status_code, body, tenant_id=None):
                raise RuntimeError("idempotency write failed")

            async def close(self):
                return None

        ctx = self.client.app.state.api_context
        ctx.idempotency = FailingIdempotencyStore()
        ctx._idempotency_owned = False

        response = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={"inputs": {}},
            headers=self._with_project({"Idempotency-Key": "idem_run_fail_open", **auth_headers}),
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload.get("run_id"))
        self.assertEqual(payload.get("status"), "COMPLETED")

    def test_capability_registry_create_and_list_versions(self):
        create_response = self.client.post(
            "/capabilities",
            json={
                "capability_id": "cap_agent_triage",
                "version": "1.0.0",
                "node_type": "agent",
                "contract": {
                    "inputs": {"type": "object"},
                    "outputs": {"type": "object"},
                    "constraints": {"timeout_s": 20},
                    "retry_policy": {"max_retries": 1},
                    "error_codes": ["ERR_TIMEOUT"],
                },
            },
        )
        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()
        self.assertEqual(created["capability_id"], "cap_agent_triage")
        self.assertEqual(created["version"], "1.0.0")

        list_response = self.client.get("/capabilities", params={"capability_id": "cap_agent_triage"})
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()["items"]), 1)

        versions_response = self.client.get("/capabilities/cap_agent_triage/versions")
        self.assertEqual(versions_response.status_code, 200)
        self.assertEqual(len(versions_response.json()["items"]), 1)
        self.assertEqual(versions_response.json()["items"][0]["version"], "1.0.0")

    def test_publish_rejects_unknown_capability_pin(self):
        headers = self._with_project()
        draft = {
            "nodes": [
                {"id": "start", "type": "start"},
                {
                    "id": "agent_1",
                    "type": "agent",
                    "config": {
                        "instructions": "Classify",
                        "capability_id": "cap_missing",
                        "capability_version": "9.9.9",
                    },
                },
                {"id": "end", "type": "end"},
            ],
            "edges": [
                {"source": "start", "target": "agent_1"},
                {"source": "agent_1", "target": "end"},
            ],
            "variables_schema": {},
        }
        create_response = self.client.post("/workflows", json={"name": "Pinned capability wf", "draft": draft}, headers=headers)
        self.assertEqual(create_response.status_code, 201)
        workflow_id = create_response.json()["workflow_id"]

        publish_response = self.client.post(f"/workflows/{workflow_id}/publish", headers=headers)
        self.assertEqual(publish_response.status_code, 400)
        error = publish_response.json()["error"]
        self.assertEqual(error["code"], "INVALID_ARGUMENT")
        details = error.get("details") or []
        self.assertTrue(any("unknown capability cap_missing@9.9.9" in item for item in details))

    def test_start_run_with_pinned_capability_writes_ledger(self):
        headers = self._with_project()
        capability_response = self.client.post(
            "/capabilities",
            json={
                "capability_id": "cap_agent_mock",
                "version": "1.0.0",
                "node_type": "agent",
                "contract": {
                    "constraints": {"timeout_s": 30},
                    "retry_policy": {"max_retries": 0},
                    "error_codes": [],
                },
            },
            headers=headers,
        )
        self.assertEqual(capability_response.status_code, 201)

        draft = {
            "nodes": [
                {"id": "start", "type": "start"},
                {
                    "id": "agent_1",
                    "type": "agent",
                    "config": {
                        "instructions": "Return short answer",
                        "capability_id": "cap_agent_mock",
                        "capability_version": "1.0.0",
                    },
                },
                {"id": "end", "type": "end"},
            ],
            "edges": [
                {"source": "start", "target": "agent_1"},
                {"source": "agent_1", "target": "end"},
            ],
            "variables_schema": {},
        }
        create_response = self.client.post("/workflows", json={"name": "Ledger wf", "draft": draft}, headers=headers)
        self.assertEqual(create_response.status_code, 201)
        workflow_id = create_response.json()["workflow_id"]
        publish_response = self.client.post(f"/workflows/{workflow_id}/publish", headers=headers)
        self.assertEqual(publish_response.status_code, 200)

        run_response = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={"inputs": {}, "mode": "test"},
            headers=headers,
        )
        self.assertEqual(run_response.status_code, 201)
        run_id = run_response.json()["run_id"]

        ledger_response = self.client.get(f"/runs/{run_id}/ledger", headers=headers)
        self.assertEqual(ledger_response.status_code, 200)
        items = ledger_response.json()["items"]
        self.assertTrue(items)
        self.assertTrue(any(item.get("event_type") == "node_started" for item in items))
        self.assertTrue(
            any(
                item.get("step_id") == "agent_1"
                and item.get("capability_id") == "cap_agent_mock"
                and item.get("capability_version") == "1.0.0"
                for item in items
            )
        )

    def test_start_run_persists_run_before_ledger_append(self):
        workflow_id, _ = self._create_workflow()
        self.client.get("/health")
        ctx = self.client.app.state.api_context
        asyncio.run(ctx.ensure_run_store())
        guard_store = GuardRunVisibilityLedgerStore(ctx.run_store)
        ctx.run_ledger_store = guard_store

        run_response = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={"inputs": {}},
            headers=self._with_project(),
        )
        self.assertEqual(run_response.status_code, 201)
        self.assertGreaterEqual(guard_store.calls, 1)

    def test_start_run_retries_ledger_write_on_fk_race(self):
        workflow_id, _ = self._create_workflow()
        self.client.get("/health")
        ctx = self.client.app.state.api_context
        asyncio.run(ctx.ensure_run_store())
        flaky_store = FlakyFkLedgerStore(failures_before_success=2)
        ctx.run_ledger_store = flaky_store

        run_response = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={"inputs": {}},
            headers=self._with_project(),
        )
        self.assertEqual(run_response.status_code, 201)
        self.assertEqual(flaky_store.calls, 3)

    def test_orchestrator_message_fk_race_error_includes_run_id_details(self):
        project_id = "proj_fk_race"
        headers = self._with_project(project_id=project_id)
        workflow_id, _ = self._create_workflow(headers=headers)
        self._bootstrap_project(
            project_id=project_id,
            workflow_defs=[
                {
                    "workflow_id": workflow_id,
                    "name": "FK Race workflow",
                    "description": "FK race repro",
                    "tags": ["fk", "race"],
                    "examples": ["start fk race"],
                }
            ],
        )
        self.client.get("/health")
        ctx = self.client.app.state.api_context
        ctx.run_ledger_store = AlwaysFailFkLedgerStore()

        response = self.client.post(
            "/orchestrator/messages",
            json={
                "session_id": "s_fk_race",
                "user_id": "u_fk_race",
                "project_id": project_id,
                "workflow_id": workflow_id,
                "message": {"id": "m_fk_race_1", "text": "start"},
                "metadata": {"locale": "ru-RU"},
            },
        )
        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "ERR_WORKFLOW_ENGINE_UNAVAILABLE")
        details = payload["error"].get("details") or {}
        self.assertEqual(details.get("incident_code"), "RUN_LEDGER_RUN_NOT_VISIBLE")
        self.assertTrue(details.get("run_id"))
        self.assertNotIn("run_ledger_run_id_fkey", payload["error"]["message"])

    def test_handoff_package_create_and_deterministic_replay(self):
        workflow_id, version_id = self._create_workflow()
        headers = self._with_project()
        create_response = self.client.post(
            "/handoff/packages",
            json={
                "workflow_id": workflow_id,
                "version_id": version_id,
                "replay_mode": "deterministic",
                "package": {
                    "context": {"input": "hello"},
                    "constraints": {"latency_ms": 5000},
                    "expected_result": {"status": "completed"},
                    "acceptance_checks": [{"id": "run_completed", "type": "status_equals", "value": "COMPLETED"}],
                },
            },
            headers=headers,
        )
        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()
        self.assertEqual(created["replay_mode"], "deterministic")
        self.assertEqual(created["status"], "STARTED")
        self.assertTrue(created.get("handoff_id"))
        first_run_id = created.get("run_id")
        self.assertTrue(first_run_id)

        replay_response = self.client.post(
            f"/handoff/packages/{created['handoff_id']}/replay",
            headers=headers,
        )
        self.assertEqual(replay_response.status_code, 200)
        replayed = replay_response.json()
        self.assertEqual(replayed["status"], "REPLAYED")
        self.assertTrue(replayed.get("run_id"))
        self.assertNotEqual(first_run_id, replayed.get("run_id"))

    def test_sse_snapshot(self):
        workflow_id, _ = self._create_workflow()
        response = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={"inputs": {}},
            headers=self._with_project(),
        )
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
        response = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={"inputs": {}},
            headers=self._with_project(),
        )
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
        response = self.client.post(
            "/workflows",
            json={"name": "Invalid workflow", "draft": bad_draft},
            headers=self._with_project(),
        )
        self.assertEqual(response.status_code, 201)
        workflow_id = response.json()["workflow_id"]

        publish_response = self.client.post(
            f"/workflows/{workflow_id}/publish",
            headers=self._with_project(),
        )
        self.assertEqual(publish_response.status_code, 400)
        error = publish_response.json()["error"]
        self.assertEqual(error["code"], "INVALID_ARGUMENT")

    def test_list_workflows(self):
        draft = {
            "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}],
            "edges": [{"source": "start", "target": "end"}],
            "variables_schema": {},
        }
        response_a = self.client.post(
            "/workflows",
            json={"name": "List A", "draft": draft},
            headers=self._with_project(project_id="proj_list"),
        )
        response_b = self.client.post(
            "/workflows",
            json={"name": "List B", "draft": draft},
            headers=self._with_project(project_id="proj_list"),
        )
        self.assertEqual(response_a.status_code, 201)
        self.assertEqual(response_b.status_code, 201)

        list_response = self.client.get("/workflows", headers=self._with_project(project_id="proj_list"))
        self.assertEqual(list_response.status_code, 200)
        payload = list_response.json()
        self.assertIn("items", payload)
        self.assertGreaterEqual(len(payload["items"]), 2)
        item = payload["items"][0]
        self.assertIn("workflow_id", item)
        self.assertIn("name", item)
        self.assertNotIn("draft", item)

    def test_workflow_endpoints_require_project_header(self):
        draft = {
            "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}],
            "edges": [{"source": "start", "target": "end"}],
            "variables_schema": {},
        }
        create_response = self.client.post("/workflows", json={"name": "No project", "draft": draft})
        self.assertEqual(create_response.status_code, 422)
        self.assertEqual(create_response.json()["error"]["code"], "ERR_PROJECT_ID_REQUIRED")

        list_response = self.client.get("/workflows")
        self.assertEqual(list_response.status_code, 422)
        self.assertEqual(list_response.json()["error"]["code"], "ERR_PROJECT_ID_REQUIRED")

    def test_workflow_project_isolation_within_tenant(self):
        draft = {
            "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}],
            "edges": [{"source": "start", "target": "end"}],
            "variables_schema": {},
        }
        response_a = self.client.post(
            "/workflows",
            json={"name": "Project A", "draft": draft},
            headers=self._with_project(project_id="proj_a"),
        )
        response_b = self.client.post(
            "/workflows",
            json={"name": "Project B", "draft": draft},
            headers=self._with_project(project_id="proj_b"),
        )
        self.assertEqual(response_a.status_code, 201)
        self.assertEqual(response_b.status_code, 201)
        workflow_a = response_a.json()["workflow_id"]

        list_a = self.client.get("/workflows", headers=self._with_project(project_id="proj_a"))
        list_b = self.client.get("/workflows", headers=self._with_project(project_id="proj_b"))
        self.assertEqual(len(list_a.json()["items"]), 1)
        self.assertEqual(len(list_b.json()["items"]), 1)
        self.assertEqual(list_a.json()["items"][0]["project_id"], "proj_a")
        self.assertEqual(list_b.json()["items"][0]["project_id"], "proj_b")

        cross_get = self.client.get(
            f"/workflows/{workflow_a}",
            headers=self._with_project(project_id="proj_b"),
        )
        self.assertEqual(cross_get.status_code, 404)

    def test_update_workflow_meta(self):
        workflow_id, _ = self._create_workflow()
        response = self.client.patch(
            f"/workflows/{workflow_id}",
            json={"name": "Renamed workflow", "description": "Updated description"},
            headers=self._with_project(),
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
        response = self.client.put(
            f"/workflows/{workflow_id}/draft",
            json=draft,
            headers=self._with_project(),
        )
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
        workflow = self.client.post(
            "/workflows",
            json={"name": "Interrupt workflow", "draft": draft},
            headers=self._with_project(),
        )
        self.assertEqual(workflow.status_code, 201)
        workflow_id = workflow.json()["workflow_id"]
        self.client.post(
            f"/workflows/{workflow_id}/publish",
            headers=self._with_project(),
        )

        run_response = self.client.post(
            f"/workflows/{workflow_id}/runs",
            json={"inputs": {}},
            headers=self._with_project(),
        )
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
        response = self.client.get("/workflows/missing", headers=self._with_project())
        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertIn("correlation_id", payload)
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")

    def test_start_run_unhandled_exception_returns_json_error_envelope(self):
        workflow_store = InMemoryWorkflowStore()
        artifact_store = InMemoryArtifactStore()
        with TestClient(
            create_app(workflow_store=workflow_store, artifact_store=artifact_store),
            raise_server_exceptions=False,
        ) as client:
            headers = {"X-Project-Id": "proj_unhandled", "X-Correlation-Id": "corr_unhandled"}
            token = os.getenv("WORKCORE_API_AUTH_TOKEN")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            draft = {
                "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}],
                "edges": [{"source": "start", "target": "end"}],
                "variables_schema": {},
            }
            create_response = client.post("/workflows", json={"name": "Unhandled workflow", "draft": draft}, headers=headers)
            self.assertEqual(create_response.status_code, 201)
            workflow_id = create_response.json()["workflow_id"]
            publish_response = client.post(f"/workflows/{workflow_id}/publish", headers=headers)
            self.assertEqual(publish_response.status_code, 200)

            run_store = client.app.state.api_context.run_store
            original_save = run_store.save

            def _boom(*args, **kwargs):
                raise RuntimeError("run store unavailable")

            run_store.save = _boom
            try:
                response = client.post(
                    f"/workflows/{workflow_id}/runs",
                    json={"inputs": {}},
                    headers=headers,
                )
            finally:
                run_store.save = original_save

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers.get("content-type"), "application/json")
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "INTERNAL")
        self.assertEqual(payload["correlation_id"], "corr_unhandled")

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
        self.assertIn("/projects", markdown_response.text)
        self.assertIn("/projects/{project_id}/orchestrators", markdown_response.text)
        self.assertIn("/projects/{project_id}/workflow-definitions", markdown_response.text)
        self.assertIn("/agent-integration-logs", markdown_response.text)
        self.assertIn("API changelog policy", markdown_response.text)
        self.assertIn("Previous API version", markdown_response.text)
        self.assertIn("Current API version", markdown_response.text)
        self.assertIn("Special instructions and examples", markdown_response.text)
        self.assertIn("set_state.assignments[]", markdown_response.text)
        self.assertIn("Example: project bootstrap + registry binding", markdown_response.text)
        self.assertIn("Example: orchestrator message", markdown_response.text)

        json_response = self.client.get("/agent-integration-kit.json")
        self.assertEqual(json_response.status_code, 200)
        payload = json_response.json()
        self.assertEqual(payload["title"], "WorkCore Agent Integration Kit")
        self.assertIn("urls", payload)
        self.assertIn("schemas", payload)
        self.assertIn("integration_logs", payload["urls"])
        self.assertIn("projects_list", payload["urls"])
        self.assertIn("projects_create", payload["urls"])
        self.assertIn("project_orchestrator_upsert_template", payload["urls"])
        self.assertIn("project_workflow_definition_upsert_template", payload["urls"])
        self.assertEqual(
            payload["schemas"]["workflow_export_v1"]["properties"]["schema_version"]["const"],
            "workflow_export_v1",
        )

        guide_response = self.client.get("/workflow-authoring-guide")
        self.assertEqual(guide_response.status_code, 200)
        self.assertIn("Workflow Authoring Guide for Agents", guide_response.text)

        draft_schema_response = self.client.get("/schemas/workflow-draft.schema.json")
        self.assertEqual(draft_schema_response.status_code, 200)
        draft_schema_payload = draft_schema_response.json()
        self.assertEqual(draft_schema_payload["title"], "WorkCore Workflow Draft")
        self.assertIn("assignments", draft_schema_payload["$defs"]["setStateConfig"]["properties"])
        self.assertIn("integration_http", draft_schema_payload["$defs"]["nodeType"]["enum"])

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
        self.assertTrue(
            any(check.get("id") == "draft_schema_set_state_batch_assignments" for check in report["checks"])
        )
        self.assertIn("projects_list", report["urls"])
        self.assertIn("projects_create", report["urls"])
        self.assertIn("project_orchestrator_upsert_template", report["urls"])
        self.assertIn("project_workflow_definition_upsert_template", report["urls"])

        integration_logs = self.client.get("/agent-integration-logs")
        self.assertEqual(integration_logs.status_code, 200)
        log_payload = integration_logs.json()
        self.assertEqual(log_payload["title"], "WorkCore Agent Integration Logs")
        self.assertGreater(log_payload["summary"]["returned"], 0)
        self.assertTrue(any(item["event"] == "integration.kit.read" for item in log_payload["entries"]))

        first_corr_id = log_payload["entries"][0].get("correlation_id")
        if first_corr_id:
            filtered_logs = self.client.get(
                "/agent-integration-logs",
                params={"correlation_id": first_corr_id, "limit": 50},
            )
            self.assertEqual(filtered_logs.status_code, 200)
            filtered_payload = filtered_logs.json()
            self.assertTrue(all(item.get("correlation_id") == first_corr_id for item in filtered_payload["entries"]))

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

        valid_batch_set_state = self.client.post(
            "/agent-integration-test/validate-draft",
            json={
                "draft": {
                    "nodes": [
                        {"id": "start", "type": "start"},
                        {
                            "id": "set",
                            "type": "set_state",
                            "config": {
                                "assignments": [
                                    {"target": "budget.base", "expression": "inputs['amount']"},
                                    {"target": "budget.total", "expression": "state['budget']['base'] + 10"},
                                ]
                            },
                        },
                        {"id": "end", "type": "end"},
                    ],
                    "edges": [{"source": "start", "target": "set"}, {"source": "set", "target": "end"}],
                    "variables_schema": {},
                }
            },
        )
        self.assertEqual(valid_batch_set_state.status_code, 200)
        self.assertTrue(valid_batch_set_state.json()["valid"])

        invalid_draft_response = self.client.post(
            "/agent-integration-test/validate-draft",
            json={"draft": {"nodes": [{"id": "start", "type": "start"}], "edges": []}},
        )
        self.assertEqual(invalid_draft_response.status_code, 200)
        self.assertFalse(invalid_draft_response.json()["valid"])
        self.assertGreater(len(invalid_draft_response.json()["errors"]), 0)

    def test_agent_integration_logs_reject_invalid_limit(self):
        response = self.client.get("/agent-integration-logs", params={"limit": "bad"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_ARGUMENT")

        too_large = self.client.get("/agent-integration-logs", params={"limit": 9999})
        self.assertEqual(too_large.status_code, 400)
        self.assertEqual(too_large.json()["error"]["code"], "INVALID_ARGUMENT")

    def test_delete_workflow(self):
        workflow_id, _ = self._create_workflow()
        delete_response = self.client.delete(
            f"/workflows/{workflow_id}",
            headers=self._with_project(),
        )
        self.assertEqual(delete_response.status_code, 204)

        get_response = self.client.get(
            f"/workflows/{workflow_id}",
            headers=self._with_project(),
        )
        self.assertEqual(get_response.status_code, 404)

    def test_tenant_isolation_for_workflows_and_runs(self):
        headers_a = {"X-Tenant-Id": "tenant_a", "X-Project-Id": "proj_tenant"}
        headers_b = {"X-Tenant-Id": "tenant_b", "X-Project-Id": "proj_tenant"}
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
        unauthorized_list = self.client.get("/projects")
        self.assertEqual(unauthorized_list.status_code, 401)
        self.assertEqual(unauthorized_list.json()["error"]["code"], "UNAUTHORIZED")

        unauthorized_project = self.client.post(
            "/projects",
            json={"project_id": "proj_auth_blocked", "project_name": "Auth Blocked"},
        )
        self.assertEqual(unauthorized_project.status_code, 401)
        self.assertEqual(unauthorized_project.json()["error"]["code"], "UNAUTHORIZED")

        authorized_list = self.client.get(
            "/projects",
            headers={"Authorization": "Bearer test_api_token"},
        )
        self.assertEqual(authorized_list.status_code, 200)

        authorized_project = self.client.post(
            "/projects",
            json={"project_id": "proj_auth_allowed", "project_name": "Auth Allowed"},
            headers={"Authorization": "Bearer test_api_token"},
        )
        self.assertEqual(authorized_project.status_code, 201)

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
            headers={"Authorization": "Bearer test_api_token", "X-Project-Id": "proj_auth"},
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

        logs_response = self.client.get("/agent-integration-logs")
        self.assertEqual(logs_response.status_code, 401)
        self.assertEqual(logs_response.json()["error"]["code"], "UNAUTHORIZED")

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


class ApiCorsTests(unittest.TestCase):
    def setUp(self):
        self._previous_cors = os.environ.get("CORS_ALLOW_ORIGINS")
        os.environ["CORS_ALLOW_ORIGINS"] = "http://workcore.build:8080,https://workcore.build:8443"
        self.client = TestClient(create_app(workflow_store=InMemoryWorkflowStore()))

    def tearDown(self):
        if self._previous_cors is None:
            os.environ.pop("CORS_ALLOW_ORIGINS", None)
        else:
            os.environ["CORS_ALLOW_ORIGINS"] = self._previous_cors

    def test_preflight_allows_configured_origin(self):
        response = self.client.options(
            "/workflows",
            headers={
                "Origin": "http://workcore.build:8080",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://workcore.build:8080")

    def test_preflight_rejects_unknown_origin(self):
        response = self.client.options(
            "/workflows",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertNotEqual(response.headers.get("access-control-allow-origin"), "http://evil.example")

    def test_preflight_allows_default_workcore_https_origin(self):
        with mock.patch.dict(os.environ, {"CORS_ALLOW_ORIGINS": ""}, clear=False):
            client = TestClient(create_app(workflow_store=InMemoryWorkflowStore()))
            response = client.options(
                "/workflows",
                headers={
                    "Origin": "https://workcore.build",
                    "Access-Control-Request-Method": "POST",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "https://workcore.build")


class ApiSecurityEnvValidationTests(unittest.TestCase):
    def test_validate_runtime_security_env_requires_bearer_token(self):
        env = {
            "WORKCORE_ALLOW_INSECURE_DEV": "0",
            "WEBHOOK_DEFAULT_INBOUND_SECRET": "secret_ok",
            "CORS_ALLOW_ORIGINS": "http://workcore.build:8080",
        }

        def getter(name: str, default=None):
            return env.get(name, default)

        with self.assertRaises(RuntimeError):
            with mock.patch("apps.orchestrator.api.app.get_env", side_effect=getter):
                validate_runtime_security_env()

    def test_validate_runtime_security_env_requires_webhook_secret(self):
        env = {
            "WORKCORE_ALLOW_INSECURE_DEV": "0",
            "WORKCORE_API_AUTH_TOKEN": "token_ok",
            "CORS_ALLOW_ORIGINS": "http://workcore.build:8080",
        }

        def getter(name: str, default=None):
            return env.get(name, default)

        with self.assertRaises(RuntimeError):
            with mock.patch("apps.orchestrator.api.app.get_env", side_effect=getter):
                validate_runtime_security_env()

    def test_validate_runtime_security_env_rejects_wildcard_cors(self):
        env = {
            "WORKCORE_ALLOW_INSECURE_DEV": "0",
            "WORKCORE_API_AUTH_TOKEN": "token_ok",
            "WEBHOOK_DEFAULT_INBOUND_SECRET": "secret_ok",
            "CORS_ALLOW_ORIGINS": "https://workcore.build,*",
        }

        def getter(name: str, default=None):
            return env.get(name, default)

        with self.assertRaises(RuntimeError):
            with mock.patch("apps.orchestrator.api.app.get_env", side_effect=getter):
                validate_runtime_security_env()

    def test_validate_runtime_security_env_allows_insecure_override(self):
        env = {"WORKCORE_ALLOW_INSECURE_DEV": "1"}

        def getter(name: str, default=None):
            return env.get(name, default)

        with mock.patch("apps.orchestrator.api.app.get_env", side_effect=getter):
            validate_runtime_security_env()


if __name__ == "__main__":
    unittest.main()
