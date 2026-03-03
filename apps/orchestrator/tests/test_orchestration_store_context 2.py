import unittest

from apps.orchestrator.orchestrator_runtime import InMemoryOrchestrationStore


class OrchestrationStoreContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_get_unset_context_values(self):
        store = InMemoryOrchestrationStore()

        await store.set_context_values(
            "session",
            "sess_1",
            values={"profile_id": "p_1", "plan": "gold"},
            tenant_id="tenant_a",
            project_id="proj_a",
        )

        loaded = await store.get_context_values(
            "session",
            "sess_1",
            tenant_id="tenant_a",
            project_id="proj_a",
        )
        self.assertEqual(loaded["profile_id"], "p_1")
        self.assertEqual(loaded["plan"], "gold")

        removed = await store.unset_context_keys(
            "session",
            "sess_1",
            keys=["plan"],
            tenant_id="tenant_a",
            project_id="proj_a",
        )
        self.assertEqual(removed, ["plan"])

        loaded_after = await store.get_context_values(
            "session",
            "sess_1",
            tenant_id="tenant_a",
            project_id="proj_a",
        )
        self.assertEqual(loaded_after, {"profile_id": "p_1"})

    async def test_context_is_project_scoped_when_project_id_is_set(self):
        store = InMemoryOrchestrationStore()

        await store.set_context_values(
            "session",
            "sess_shared",
            values={"value": "proj_a"},
            tenant_id="tenant_a",
            project_id="proj_a",
        )
        await store.set_context_values(
            "session",
            "sess_shared",
            values={"value": "proj_b"},
            tenant_id="tenant_a",
            project_id="proj_b",
        )

        proj_a = await store.get_context_values(
            "session",
            "sess_shared",
            tenant_id="tenant_a",
            project_id="proj_a",
        )
        proj_b = await store.get_context_values(
            "session",
            "sess_shared",
            tenant_id="tenant_a",
            project_id="proj_b",
        )

        self.assertEqual(proj_a, {"value": "proj_a"})
        self.assertEqual(proj_b, {"value": "proj_b"})


if __name__ == "__main__":
    unittest.main()
