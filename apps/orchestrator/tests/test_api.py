import asyncio
import os
import unittest
from unittest import mock

from starlette.testclient import TestClient

from apps.orchestrator.api import create_app
from apps.orchestrator.api.app import validate_runtime_security_env
from apps.orchestrator.api.workflow_store import InMemoryWorkflowStore
from apps.orchestrator.streaming.sse import _event_stream


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.workflow_store = InMemoryWorkflowStore()
        self.default_project_id = "proj_test"
        self.client = TestClient(create_app(workflow_store=self.workflow_store))

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
                default_orchestrator_id=orchestrator_id,
                settings={"orchestrator_enabled": True},
            )
            await store.upsert_orchestrator_config(
                project_id=project_id,
                orchestrator_id=orchestrator_id,
                name="Default orchestrator",
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
                "settings": {"orchestrator_enabled": True},
            },
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["project_id"], "proj_new")
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

        bad_settings = self.client.post("/projects", json={"project_id": "proj_bad_settings", "settings": "bad"})
        self.assertEqual(bad_settings.status_code, 400)
        self.assertEqual(bad_settings.json()["error"]["code"], "INVALID_ARGUMENT")

    def test_create_project_returns_conflict_when_duplicate(self):
        first = self.client.post("/projects", json={"project_id": "proj_dup"})
        self.assertEqual(first.status_code, 201)
        second = self.client.post("/projects", json={"project_id": "proj_dup"})
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["error"]["code"], "CONFLICT")

    def test_upsert_project_workflow_definition_enables_direct_orchestrator_mode(self):
        project_id = "proj_registry_direct"
        workflow_headers = self._with_project(project_id=project_id)
        workflow_id, _ = self._create_workflow(headers=workflow_headers)

        project_response = self.client.post(
            "/projects",
            json={
                "project_id": project_id,
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

    def test_upsert_project_workflow_definition_validates_scope(self):
        project_id = "proj_registry_scope"
        self.client.post(
            "/projects",
            json={
                "project_id": project_id,
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
        self.assertTrue(payload.get("run_id"))

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

        json_response = self.client.get("/agent-integration-kit.json")
        self.assertEqual(json_response.status_code, 200)
        payload = json_response.json()
        self.assertEqual(payload["title"], "WorkCore Agent Integration Kit")
        self.assertIn("urls", payload)
        self.assertIn("schemas", payload)
        self.assertIn("integration_logs", payload["urls"])
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
        unauthorized_project = self.client.post("/projects", json={"project_id": "proj_auth_blocked"})
        self.assertEqual(unauthorized_project.status_code, 401)
        self.assertEqual(unauthorized_project.json()["error"]["code"], "UNAUTHORIZED")

        authorized_project = self.client.post(
            "/projects",
            json={"project_id": "proj_auth_allowed"},
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
        self.assertEqual(logs_response.status_code, 200)

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
