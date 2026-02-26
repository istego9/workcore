import unittest
from unittest import mock

from apps.orchestrator.executors.types import ExecutorResult
from apps.orchestrator.runtime import Edge, MultiWorkflowRuntimeService, Node, SimpleEvaluator, Workflow


class MultiWorkflowRuntimeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_run_offloads_engine_execution_to_worker_thread(self):
        nodes = [
            Node("start", "start"),
            Node("end", "end"),
        ]
        edges = [Edge("start", "end")]
        workflow = Workflow(
            id="wf_multi_thread_offload",
            version_id="v1",
            nodes={node.id: node for node in nodes},
            edges=edges,
        )

        async def loader(workflow_id: str, version_id: str | None, tenant_id: str | None = None):
            if workflow_id != workflow.id:
                raise RuntimeError("unknown workflow")
            return workflow

        service = MultiWorkflowRuntimeService.create(workflow_loader=loader, evaluator=SimpleEvaluator())

        async def _to_thread_passthrough(func, *args, **kwargs):
            return func(*args, **kwargs)

        with mock.patch(
            "apps.orchestrator.runtime.multi_service.asyncio.to_thread",
            new=mock.AsyncMock(side_effect=_to_thread_passthrough),
        ) as to_thread_mock:
            run = await service.start_run(workflow.id, workflow.version_id, inputs={"seed": "ok"})

        self.assertEqual(run.status, "COMPLETED")
        self.assertGreaterEqual(to_thread_mock.await_count, 1)
        first_fn = to_thread_mock.await_args_list[0].args[0]
        self.assertEqual(getattr(first_fn, "__name__", ""), "execute_until_blocked")

    async def test_capability_defaults_apply_for_integration_http_without_overriding_explicit_values(self):
        captured = {}

        class FakeIntegrationExecutor:
            def __call__(self, run, node, emit):
                captured["config"] = dict(node.config or {})
                return ExecutorResult(output={"ok": True})

        nodes = [
            Node("start", "start"),
            Node(
                "http_node",
                "integration_http",
                config={
                    "url": "https://api.example.com/v1/data",
                    "method": "POST",
                },
            ),
            Node("end", "end"),
        ]
        edges = [Edge("start", "http_node"), Edge("http_node", "end")]
        workflow = Workflow(
            id="wf_http_defaults",
            version_id="v1",
            nodes={node.id: node for node in nodes},
            edges=edges,
        )

        async def loader(workflow_id: str, version_id: str | None, tenant_id: str | None = None):
            return workflow

        async def resolve_capability(_tenant: str, _capability_id: str, _version: str):
            return {
                "constraints": {
                    "integration_http_defaults": {
                        "method": "GET",
                        "timeout_s": 15,
                        "retry_attempts": 2,
                        "auth": {
                            "type": "bearer",
                            "token_env": "INTEGRATION_TOKEN",
                        },
                    }
                }
            }

        workflow.nodes["http_node"].config["capability_id"] = "cap_http"
        workflow.nodes["http_node"].config["capability_version"] = "1.0.0"

        service = MultiWorkflowRuntimeService.create(
            workflow_loader=loader,
            evaluator=SimpleEvaluator(),
            executors={"integration_http": FakeIntegrationExecutor()},
            resolve_capability=resolve_capability,
        )
        run = await service.start_run(workflow.id, workflow.version_id, inputs={})
        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(captured["config"]["method"], "POST")
        self.assertEqual(captured["config"]["timeout_s"], 15)
        self.assertEqual(captured["config"]["retry_attempts"], 2)
        self.assertEqual(captured["config"]["auth"]["token_env"], "INTEGRATION_TOKEN")

    async def test_capability_defaults_apply_for_mcp_node(self):
        captured = {}

        class FakeMCPExecutor:
            def __call__(self, run, node, emit):
                captured["config"] = dict(node.config or {})
                return ExecutorResult(output={"ok": True})

        nodes = [
            Node("start", "start"),
            Node(
                "mcp_node",
                "mcp",
                config={
                    "tool": "echo",
                    "arguments": {"ping": True},
                },
            ),
            Node("end", "end"),
        ]
        edges = [Edge("start", "mcp_node"), Edge("mcp_node", "end")]
        workflow = Workflow(
            id="wf_mcp_defaults",
            version_id="v1",
            nodes={node.id: node for node in nodes},
            edges=edges,
        )

        async def loader(workflow_id: str, version_id: str | None, tenant_id: str | None = None):
            return workflow

        async def resolve_capability(_tenant: str, _capability_id: str, _version: str):
            return {
                "constraints": {
                    "mcp_defaults": {
                        "server": "default_server",
                        "timeout_s": 22,
                        "allowed_tools": ["echo"],
                    }
                }
            }

        workflow.nodes["mcp_node"].config["capability_id"] = "cap_mcp"
        workflow.nodes["mcp_node"].config["capability_version"] = "1.0.0"

        service = MultiWorkflowRuntimeService.create(
            workflow_loader=loader,
            evaluator=SimpleEvaluator(),
            executors={"mcp": FakeMCPExecutor()},
            resolve_capability=resolve_capability,
        )
        run = await service.start_run(workflow.id, workflow.version_id, inputs={})
        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(captured["config"]["server"], "default_server")
        self.assertEqual(captured["config"]["timeout_s"], 22)
        self.assertEqual(captured["config"]["allowed_tools"], ["echo"])

    async def test_capability_defaults_reject_inline_auth_secrets(self):
        nodes = [
            Node("start", "start"),
            Node(
                "http_node",
                "integration_http",
                config={
                    "url": "https://api.example.com/v1/data",
                    "capability_id": "cap_http_bad",
                    "capability_version": "1.0.0",
                },
            ),
            Node("end", "end"),
        ]
        edges = [Edge("start", "http_node"), Edge("http_node", "end")]
        workflow = Workflow(
            id="wf_http_bad_defaults",
            version_id="v1",
            nodes={node.id: node for node in nodes},
            edges=edges,
        )

        async def loader(workflow_id: str, version_id: str | None, tenant_id: str | None = None):
            return workflow

        async def resolve_capability(_tenant: str, _capability_id: str, _version: str):
            return {
                "constraints": {
                    "integration_http_defaults": {
                        "auth": {
                            "type": "bearer",
                            "token": "inline-secret-token",
                        }
                    }
                }
            }

        class FakeIntegrationExecutor:
            def __call__(self, run, node, emit):
                return ExecutorResult(output={"ok": True})

        service = MultiWorkflowRuntimeService.create(
            workflow_loader=loader,
            evaluator=SimpleEvaluator(),
            executors={"integration_http": FakeIntegrationExecutor()},
            resolve_capability=resolve_capability,
        )

        with self.assertRaises(ValueError):
            await service.start_run(workflow.id, workflow.version_id, inputs={})


if __name__ == "__main__":
    unittest.main()
