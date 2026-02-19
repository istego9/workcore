import json
import unittest

from apps.orchestrator.api.idempotency import InMemoryIdempotencyStore, PostgresIdempotencyStore


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

    async def test_postgres_store_set_sanitizes_nul_bytes_in_response_body(self):
        class CapturePool:
            def __init__(self) -> None:
                self.calls = []

            async def execute(self, *args):
                self.calls.append(args)
                return "INSERT 0 1"

        pool = CapturePool()
        store = PostgresIdempotencyStore(pool=pool, tenant_id="tenant_test", ttl_s=60)
        await store.set(
            "idem_1",
            "run_start:wf_1",
            201,
            {"text": "ab\x00cd", "nested": [{"k\x00ey": "v\x00alue"}]},
            tenant_id="tenant_test",
        )
        self.assertEqual(len(pool.calls), 1)
        payload = pool.calls[0][6]
        self.assertNotIn("\\u0000", payload)
        decoded = json.loads(payload)
        self.assertEqual(decoded["body"]["text"], "abcd")
        self.assertEqual(decoded["body"]["nested"][0], {"key": "value"})


if __name__ == "__main__":
    unittest.main()
