import asyncio
import json
import unittest

from starlette.testclient import TestClient

from chatkit.actions import Action
from chatkit.server import StreamingResult
from chatkit.types import (
    InferenceOptions,
    ThreadCreateParams,
    ThreadsCreateReq,
    ThreadCustomActionParams,
    ThreadsCustomActionReq,
    UserMessageInput,
    UserMessageTextContent,
)

from apps.orchestrator.api.store import InMemoryRunStore
from apps.orchestrator.chatkit.app import create_app as create_chatkit_app
from apps.orchestrator.chatkit.context import ChatKitContext
from apps.orchestrator.chatkit.server import WorkflowChatKitServer
from apps.orchestrator.chatkit.store import InMemoryAttachmentStore, InMemoryChatKitStore
from apps.orchestrator.runtime import Edge, Node, SimpleEvaluator, Workflow
from apps.orchestrator.streaming import EventPublisher, InMemoryEventBus, InMemoryEventStore
from apps.orchestrator.chatkit.runtime_service import ChatKitRuntimeService
from apps.orchestrator.executors.types import ExecutorResult


class ChatKitTests(unittest.TestCase):
    def setUp(self):
        nodes = [
            Node("start", "start"),
            Node("approval", "approval", {"prompt": "Approve?"}),
            Node("end", "end"),
        ]
        edges = [Edge("start", "approval"), Edge("approval", "end")]
        workflow = Workflow(
            id="wf_chat",
            version_id="v1",
            nodes={node.id: node for node in nodes},
            edges=edges,
        )
        event_store = InMemoryEventStore()
        event_bus = InMemoryEventBus()
        publisher = EventPublisher(event_store, event_bus)

        async def loader(workflow_id: str, version_id: str | None, tenant_id: str):
            if workflow_id != workflow.id:
                raise RuntimeError("unknown workflow")
            return workflow

        self.service = ChatKitRuntimeService(
            publisher=publisher,
            store=event_store,
            bus=event_bus,
            evaluator=SimpleEvaluator(),
            workflow_loader=loader,
        )
        self.run_store = InMemoryRunStore()
        self.store = InMemoryChatKitStore()
        self.attachment_store = InMemoryAttachmentStore(self.store.attachments)
        self.server = WorkflowChatKitServer(self.store, self.attachment_store)
        self.workflow_id = workflow.id
        self.workflow_version_id = workflow.version_id

    def test_thread_create_emits_prompt_message(self):
        req = ThreadsCreateReq(
            metadata={"workflow_id": self.workflow_id, "workflow_version_id": self.workflow_version_id},
            params=ThreadCreateParams(
                input=UserMessageInput(
                    content=[UserMessageTextContent(text="start")],
                    attachments=[],
                    inference_options=InferenceOptions(),
                )
            )
        )
        events = asyncio.run(self._collect_events(req))
        prompt_events = [
            event
            for event in events
            if event.get("type") == "thread.item.done"
            and event.get("item", {}).get("type") == "assistant_message"
            and "Approve?" in (event.get("item", {}).get("content") or [{}])[0].get("text", "")
        ]
        self.assertTrue(prompt_events)
        widget_events = [
            event
            for event in events
            if event.get("type") == "thread.item.done"
            and event.get("item", {}).get("type") == "widget"
        ]
        self.assertTrue(widget_events)

    def test_action_resumes_interrupt(self):
        create_req = ThreadsCreateReq(
            metadata={"workflow_id": self.workflow_id, "workflow_version_id": self.workflow_version_id},
            params=ThreadCreateParams(
                input=UserMessageInput(
                    content=[UserMessageTextContent(text="start")],
                    attachments=[],
                    inference_options=InferenceOptions(),
                )
            )
        )
        create_events = asyncio.run(self._collect_events(create_req))
        thread_id = next(
            event["thread"]["id"]
            for event in create_events
            if event.get("type") == "thread.created"
        )

        run = next(iter(self.run_store.runs.values()))
        interrupt = next(iter(run.interrupts.values()))

        action_req = ThreadsCustomActionReq(
            params=ThreadCustomActionParams(
                thread_id=thread_id,
                item_id=None,
                action=Action(
                    type="interrupt.approve",
                    payload={"run_id": run.id, "interrupt_id": interrupt.id},
                ),
            )
        )

        events = asyncio.run(self._collect_events(action_req))
        completed = any(
            event.get("type") == "progress_update"
            and "completed" in event.get("text", "").lower()
            for event in events
        )
        self.assertTrue(completed)
        self.assertEqual(self.run_store.get(run.id, tenant_id="tenant_test").status, "COMPLETED")

    def test_agent_executor_is_used(self):
        nodes = [
            Node("start", "start"),
            Node("agent", "agent", {"instructions": "Hello"}),
            Node("end", "end"),
        ]
        edges = [Edge("start", "agent"), Edge("agent", "end")]
        workflow = Workflow(
            id="wf_agent",
            version_id="v1",
            nodes={node.id: node for node in nodes},
            edges=edges,
        )
        event_store = InMemoryEventStore()
        event_bus = InMemoryEventBus()
        publisher = EventPublisher(event_store, event_bus)

        async def loader(workflow_id: str, version_id: str | None, tenant_id: str):
            if workflow_id != workflow.id:
                raise RuntimeError("unknown workflow")
            return workflow

        def fake_agent_executor(run, node, emit):
            return ExecutorResult(output={"message": "hi"})

        service = ChatKitRuntimeService(
            publisher=publisher,
            store=event_store,
            bus=event_bus,
            evaluator=SimpleEvaluator(),
            workflow_loader=loader,
            executors={"agent": fake_agent_executor},
        )

        run = asyncio.run(service.start_run(workflow.id, workflow.version_id, {}, tenant_id="tenant_test"))
        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(run.node_outputs.get("agent"), {"message": "hi"})

    def test_http_chatkit_requires_tenant_header(self):
        app = create_chatkit_app(self._workflow())
        client = TestClient(app)
        req = ThreadsCreateReq(
            metadata={"workflow_id": self.workflow_id, "workflow_version_id": self.workflow_version_id},
            params=ThreadCreateParams(
                input=UserMessageInput(
                    content=[UserMessageTextContent(text="start")],
                    attachments=[],
                    inference_options=InferenceOptions(),
                )
            ),
        )
        missing_tenant = client.post("/chatkit", content=req.model_dump_json())
        self.assertEqual(missing_tenant.status_code, 422)
        self.assertEqual(missing_tenant.json()["error"]["code"], "ERR_TENANT_REQUIRED")

        with_tenant = client.post(
            "/chatkit",
            content=req.model_dump_json(),
            headers={"X-Tenant-Id": "tenant_test", "Content-Type": "application/json"},
        )
        self.assertEqual(with_tenant.status_code, 200)

    async def _collect_events(self, request) -> list[dict]:
        ctx = ChatKitContext(
            service=self.service,
            run_store=self.run_store,
            tenant_id="tenant_test",
            request_metadata=getattr(request, "metadata", None),
        )
        result = await self.server.process(request.model_dump_json(), ctx)
        self.assertIsInstance(result, StreamingResult)
        events = []
        async for chunk in result:
            if not chunk.startswith(b"data: "):
                continue
            payload = json.loads(chunk[len(b"data: ") :].strip())
            events.append(payload)
        return events

    def _workflow(self) -> Workflow:
        nodes = [
            Node("start", "start"),
            Node("approval", "approval", {"prompt": "Approve?"}),
            Node("end", "end"),
        ]
        edges = [Edge("start", "approval"), Edge("approval", "end")]
        return Workflow(
            id="wf_chat",
            version_id="v1",
            nodes={node.id: node for node in nodes},
            edges=edges,
        )


if __name__ == "__main__":
    unittest.main()
