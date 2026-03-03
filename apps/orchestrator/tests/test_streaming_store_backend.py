import unittest

from apps.orchestrator.streaming import InMemoryEventStore, create_event_store


class StreamingStoreBackendTests(unittest.TestCase):
    def test_memory_backend_is_default_store(self):
        store = create_event_store("memory")
        self.assertIsInstance(store, InMemoryEventStore)

    def test_postgres_backend_requires_pool(self):
        with self.assertRaises(RuntimeError):
            create_event_store("postgres", pool=None)

    def test_invalid_backend_raises(self):
        with self.assertRaises(RuntimeError):
            create_event_store("bad_backend")


if __name__ == "__main__":
    unittest.main()
