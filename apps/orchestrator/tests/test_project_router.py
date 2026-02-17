import unittest

from apps.orchestrator.orchestrator_runtime import InMemoryOrchestrationStore
from apps.orchestrator.project_router import ProjectRouter, ProjectRouterError, RoutingRequest


class ProjectRouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = InMemoryOrchestrationStore()
        await self.store.upsert_project(
            project_id="proj_router",
            tenant_id="local",
            default_orchestrator_id="orc_default",
            settings={"orchestrator_enabled": True},
        )
        await self.store.upsert_orchestrator_config(
            project_id="proj_router",
            orchestrator_id="orc_default",
            name="Default",
            tenant_id="local",
            routing_policy={"confidence_threshold": 0.6},
            set_as_default=True,
        )
        await self.store.upsert_workflow_definition(
            project_id="proj_router",
            workflow_id="wf_1",
            tenant_id="local",
            name="Workflow 1",
            description="Flow",
            tags=["flow"],
            examples=["start flow"],
            active=True,
        )
        self.router = ProjectRouter(self.store)

    async def test_resolve_direct_mode(self):
        request = RoutingRequest(
            session_id="s1",
            user_id="u1",
            project_id="proj_router",
            orchestrator_id=None,
            workflow_id="wf_1",
            message_id="m1",
            message_text="start",
            metadata={},
        )
        route = await self.router.resolve(request, tenant_id="local")
        self.assertEqual(route.mode, "direct")
        self.assertEqual(route.workflow_definition.workflow_id, "wf_1")

    async def test_resolve_orchestrator_mode(self):
        request = RoutingRequest(
            session_id="s1",
            user_id="u1",
            project_id="proj_router",
            orchestrator_id=None,
            workflow_id=None,
            message_id="m1",
            message_text="help",
            metadata={},
        )
        route = await self.router.resolve(request, tenant_id="local")
        self.assertEqual(route.mode, "orchestrated")
        self.assertEqual(route.orchestrator.orchestrator_id, "orc_default")

    async def test_resolve_missing_project(self):
        request = RoutingRequest(
            session_id="s1",
            user_id="u1",
            project_id="missing",
            orchestrator_id=None,
            workflow_id=None,
            message_id="m1",
            message_text="help",
            metadata={},
        )
        with self.assertRaises(ProjectRouterError) as cm:
            await self.router.resolve(request, tenant_id="local")
        self.assertEqual(cm.exception.code, "ERR_PROJECT_NOT_FOUND")

    async def test_resolve_workflow_not_in_project(self):
        request = RoutingRequest(
            session_id="s1",
            user_id="u1",
            project_id="proj_router",
            orchestrator_id=None,
            workflow_id="wf_missing",
            message_id="m1",
            message_text="help",
            metadata={},
        )
        with self.assertRaises(ProjectRouterError) as cm:
            await self.router.resolve(request, tenant_id="local")
        self.assertEqual(cm.exception.code, "ERR_WORKFLOW_NOT_IN_PROJECT")


if __name__ == "__main__":
    unittest.main()
