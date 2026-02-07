import unittest

from apps.orchestrator.api.idempotency import InMemoryIdempotencyStore


class IdempotencyStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_keys_are_scoped_by_tenant(self):
        store = InMemoryIdempotencyStore(ttl_s=60)
        await store.set("k1", "run_start:wf_1", 201, {"run_id": "run_a"}, tenant_id="tenant_a")
        await store.set("k1", "run_start:wf_1", 201, {"run_id": "run_b"}, tenant_id="tenant_b")

        cached_a = await store.get("k1", "run_start:wf_1", tenant_id="tenant_a")
        cached_b = await store.get("k1", "run_start:wf_1", tenant_id="tenant_b")

        self.assertIsNotNone(cached_a)
        self.assertIsNotNone(cached_b)
        assert cached_a is not None
        assert cached_b is not None
        self.assertEqual(cached_a.body["run_id"], "run_a")
        self.assertEqual(cached_b.body["run_id"], "run_b")


if __name__ == "__main__":
    unittest.main()
