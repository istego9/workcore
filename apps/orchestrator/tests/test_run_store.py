import os
import unittest
from pathlib import Path

import asyncpg

from apps.orchestrator.api.store import InMemoryRunStore, PostgresRunStore, create_run_store
from apps.orchestrator.api.workflow_store import PostgresWorkflowStore
from apps.orchestrator.runtime.models import Interrupt, NodeRun, Run


def _database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("CHATKIT_DATABASE_URL")


class InMemoryRunStoreTests(unittest.TestCase):
    def test_list_filters(self):
        store = InMemoryRunStore()
        run_a = Run(
            id="run_a",
            workflow_id="wf_a",
            version_id="v1",
            status="COMPLETED",
            inputs={},
            state={},
        )
        run_b = Run(
            id="run_b",
            workflow_id="wf_b",
            version_id="v1",
            status="RUNNING",
            inputs={},
            state={},
        )
        store.save(run_a)
        store.save(run_b)

        filtered = store.list(workflow_id="wf_a", status="COMPLETED")
        self.assertEqual([run.id for run in filtered], ["run_a"])

    def test_tenant_filters(self):
        store = InMemoryRunStore()
        run_a = Run(
            id="run_tenant_a",
            workflow_id="wf_a",
            version_id="v1",
            status="COMPLETED",
            inputs={},
            state={},
            metadata={"tenant_id": "tenant_a"},
        )
        run_b = Run(
            id="run_tenant_b",
            workflow_id="wf_b",
            version_id="v1",
            status="RUNNING",
            inputs={},
            state={},
            metadata={"tenant_id": "tenant_b"},
        )
        store.save(run_a)
        store.save(run_b)

        self.assertIsNotNone(store.get("run_tenant_a", tenant_id="tenant_a"))
        self.assertIsNone(store.get("run_tenant_a", tenant_id="tenant_b"))
        self.assertEqual([run.id for run in store.list(tenant_id="tenant_b")], ["run_tenant_b"])

    def test_save_sets_created_and_updated_timestamps(self):
        store = InMemoryRunStore()
        run = Run(
            id="run_with_timestamps",
            workflow_id="wf_a",
            version_id="v1",
            status="RUNNING",
            inputs={},
            state={},
        )

        store.save(run)
        created_at = run.metadata.get("created_at")
        updated_at = run.metadata.get("updated_at")

        self.assertIsInstance(created_at, str)
        self.assertIsInstance(updated_at, str)

    def test_save_applies_projection_from_metadata(self):
        store = InMemoryRunStore()
        run = Run(
            id="run_projection",
            workflow_id="wf_projection",
            version_id="v1",
            status="COMPLETED",
            inputs={},
            state={
                "documents": [
                    {
                        "doc_id": "doc_1",
                        "pages": [{"image_base64": "AAAA", "artifact_ref": "artf_1"}],
                    }
                ]
            },
            outputs={"result": {"claim_id": "clm_1", "decision": "approve"}},
            metadata={
                "state_exclude_paths": ["documents.pages.image_base64"],
                "output_include_paths": ["result.claim_id"],
            },
        )

        store.save(run)
        loaded = store.get("run_projection")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        page = loaded.state["documents"][0]["pages"][0]
        self.assertNotIn("image_base64", page)
        self.assertEqual(loaded.outputs, {"result": {"claim_id": "clm_1"}})


@unittest.skipUnless(_database_url(), "DATABASE_URL or CHATKIT_DATABASE_URL is required")
class PostgresRunStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pool = await asyncpg.create_pool(_database_url())
        await self._apply_migrations()
        await self._truncate_core_tables()
        self.workflow_store = PostgresWorkflowStore(self.pool)
        self.run_store = PostgresRunStore(self.pool)
        self.workflow_id, self.version_id = await self._create_published_workflow("Run Store Workflow")

    async def asyncTearDown(self):
        await self._truncate_core_tables()
        await self.pool.close()

    async def _apply_migrations(self) -> None:
        migrations_dir = Path(__file__).resolve().parents[3] / "db" / "migrations"
        files = sorted(migrations_dir.glob("*.sql"))
        async with self.pool.acquire() as conn:
            for path in files:
                sql = path.read_text(encoding="utf-8")
                if sql.strip():
                    await conn.execute(sql)

    async def _truncate_core_tables(self) -> None:
        await self.pool.execute(
            """
            truncate table
              node_runs,
              interrupts,
              runs,
              workflow_versions,
              workflows
            restart identity cascade
            """
        )

    async def _create_published_workflow(self, name: str) -> tuple[str, str]:
        draft = {
            "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "end"}],
            "edges": [{"source": "start", "target": "end"}],
            "variables_schema": {},
        }
        workflow = await self.workflow_store.create_workflow(name=name, description=None, draft=draft)
        version = await self.workflow_store.publish(workflow.workflow_id)
        return workflow.workflow_id, version.version_id

    async def test_roundtrip_persists_runtime_state(self):
        run = Run(
            id="run_pg_roundtrip",
            workflow_id=self.workflow_id,
            version_id=self.version_id,
            status="WAITING_FOR_INPUT",
            mode="test",
            inputs={"user": "alex"},
            state={"step": 1, "nested": {"value": "ok"}},
            metadata={
                "correlation_id": "corr_pg",
                "trace_id": "trace_pg",
                "tenant_id": "tenant_pg",
                "project_id": "proj_pg",
                "import_run_id": "imp_pg",
            },
            outputs=None,
            node_runs={
                "approval": NodeRun(
                    node_id="approval",
                    status="IN_PROGRESS",
                    attempt=2,
                    output={"partial": True},
                    last_error="temporary failure",
                    trace_id="trace_1",
                    usage={"total_tokens": 42},
                )
            },
            node_outputs={"start": {"user": "alex"}, "approval": {"partial": True}},
            interrupts={
                "intr_1": Interrupt(
                    id="intr_1",
                    run_id="run_pg_roundtrip",
                    node_id="approval",
                    type="approval",
                    status="OPEN",
                    prompt="Approve?",
                    input_schema={"type": "object"},
                    allow_file_upload=True,
                    input={"approved": True},
                    files=[{"name": "doc.txt"}],
                    state_target="approval.result",
                )
            },
            branch_selection={"if_1": "path_yes"},
            loop_state={"while_1": 3},
            skipped_nodes={"path_no"},
        )

        await self.run_store.save(run)
        loaded = await self.run_store.get(run.id, tenant_id="tenant_pg")

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.workflow_id, self.workflow_id)
        self.assertEqual(loaded.version_id, self.version_id)
        self.assertEqual(loaded.mode, "test")
        self.assertEqual(loaded.status, "WAITING_FOR_INPUT")
        self.assertEqual(loaded.inputs, {"user": "alex"})
        self.assertEqual(loaded.state, {"step": 1, "nested": {"value": "ok"}})
        self.assertEqual(loaded.metadata.get("correlation_id"), "corr_pg")
        self.assertEqual(loaded.metadata.get("trace_id"), "trace_pg")
        self.assertEqual(loaded.metadata.get("tenant_id"), "tenant_pg")
        self.assertIsInstance(loaded.metadata.get("created_at"), str)
        self.assertIsInstance(loaded.metadata.get("updated_at"), str)
        self.assertEqual(loaded.node_outputs["approval"], {"partial": True})
        self.assertEqual(loaded.branch_selection, {"if_1": "path_yes"})
        self.assertEqual(loaded.loop_state, {"while_1": 3})
        self.assertEqual(loaded.skipped_nodes, {"path_no"})

        approval_run = loaded.node_runs["approval"]
        self.assertEqual(approval_run.status, "IN_PROGRESS")
        self.assertEqual(approval_run.attempt, 2)
        self.assertEqual(approval_run.trace_id, "trace_1")
        self.assertEqual(approval_run.usage, {"total_tokens": 42})
        self.assertEqual(approval_run.last_error, "temporary failure")

        interrupt = loaded.interrupts["intr_1"]
        self.assertEqual(interrupt.type, "approval")
        self.assertEqual(interrupt.status, "OPEN")
        self.assertEqual(interrupt.state_target, "approval.result")
        self.assertEqual(interrupt.input, {"approved": True})
        self.assertEqual(interrupt.files, [{"name": "doc.txt"}])

    async def test_list_filters(self):
        run_a = Run(
            id="run_pg_a",
            workflow_id=self.workflow_id,
            version_id=self.version_id,
            status="COMPLETED",
            inputs={},
            state={},
        )
        run_b = Run(
            id="run_pg_b",
            workflow_id=self.workflow_id,
            version_id=self.version_id,
            status="RUNNING",
            inputs={},
            state={},
        )
        other_workflow_id, other_version_id = await self._create_published_workflow("Other Workflow")
        run_c = Run(
            id="run_pg_c",
            workflow_id=other_workflow_id,
            version_id=other_version_id,
            status="COMPLETED",
            inputs={},
            state={},
        )

        await self.run_store.save(run_a)
        await self.run_store.save(run_b)
        await self.run_store.save(run_c)

        completed = await self.run_store.list(workflow_id=self.workflow_id, status="COMPLETED")
        completed_ids = {run.id for run in completed}
        self.assertIn("run_pg_a", completed_ids)
        self.assertNotIn("run_pg_b", completed_ids)
        self.assertNotIn("run_pg_c", completed_ids)

    async def test_create_run_store_uses_postgres_when_pool_exists(self):
        store = await create_run_store(self.workflow_store)
        self.assertIsInstance(store, PostgresRunStore)


if __name__ == "__main__":
    unittest.main()
