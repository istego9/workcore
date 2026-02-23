from __future__ import annotations

import json
from datetime import datetime
from inspect import isawaitable
from typing import Any, AsyncIterator, Dict, List, Optional

from chatkit.actions import Action
from chatkit.server import ChatKitServer
from chatkit.types import (
    AssistantMessageContent,
    AssistantMessageItem,
    ErrorEvent,
    NoticeEvent,
    ProgressUpdateEvent,
    ThreadItemDoneEvent,
    ThreadMetadata,
    ThreadStreamEvent,
    UserMessageItem,
    WidgetItem,
)

from apps.orchestrator.runtime.models import Interrupt, Run

from .context import ChatKitContext
from .custom_actions import normalize_custom_action_payload, resolve_canonical_action_type
from .widgets import (
    APPROVE_ACTION,
    CANCEL_ACTION,
    REJECT_ACTION,
    SUBMIT_ACTION,
    approval_widget,
    interaction_widget,
)


class WorkflowChatKitServer(ChatKitServer[ChatKitContext]):
    async def respond(
        self,
        thread: ThreadMetadata,
        input_user_message: UserMessageItem | None,
        context: ChatKitContext,
    ) -> AsyncIterator[ThreadStreamEvent]:
        if input_user_message is None:
            return

        run_id = thread.metadata.get("run_id")
        run = await self._run_store_get(context, str(run_id)) if run_id else None

        if run and run.status == "WAITING_FOR_INPUT":
            interrupt = self._select_interrupt(run)
            if interrupt:
                input_data = self._input_from_message(input_user_message)
                files = self._files_from_message(input_user_message)
                run = await context.service.resume_interrupt(
                    run,
                    interrupt.id,
                    input_data,
                    files,
                    tenant_id=context.tenant_id,
                )
                await self._run_store_save(context, run)
                async for event in self._emit_run_events(run, thread, context, reuse_last=True):
                    yield event
                return

        workflow = await self._resolve_workflow(thread, context)
        if not workflow:
            yield ErrorEvent(message="workflow_id is required", allow_retry=False)
            return
        workflow_id, workflow_version_id = workflow

        inputs = self._inputs_from_message(input_user_message)
        run_metadata = dict(context.request_metadata or {})
        run_metadata["tenant_id"] = context.tenant_id
        run = await context.service.start_run(
            workflow_id,
            workflow_version_id,
            inputs,
            tenant_id=context.tenant_id,
            metadata=run_metadata,
        )
        await self._run_store_save(context, run)
        thread.metadata["run_id"] = run.id
        thread.metadata["workflow_id"] = run.workflow_id
        thread.metadata["last_event_id"] = None
        await self.store.save_thread(thread, context=context)

        async for event in self._emit_run_events(run, thread, context, reuse_last=False):
            yield event

    async def action(
        self,
        thread: ThreadMetadata,
        action: Action[str, Any],
        sender: WidgetItem | None,
        context: ChatKitContext,
    ) -> AsyncIterator[ThreadStreamEvent]:
        payload = action.payload or {}
        canonical_action_type = resolve_canonical_action_type(action.type, payload)
        if not canonical_action_type:
            yield ErrorEvent(message="unsupported action", allow_retry=False)
            return
        payload = dict(payload)
        payload.setdefault("action_type", canonical_action_type)
        run_id = payload.get("run_id") or thread.metadata.get("run_id")
        interrupt_id = payload.get("interrupt_id")

        if not run_id:
            yield ErrorEvent(message="run_id is required", allow_retry=False)
            return

        run = await self._run_store_get(context, str(run_id))
        if not run:
            yield ErrorEvent(message="run not found", allow_retry=False)
            return

        if not interrupt_id:
            interrupt = self._select_interrupt(run)
            interrupt_id = interrupt.id if interrupt else None

        if not interrupt_id:
            yield ErrorEvent(message="interrupt_id is required", allow_retry=False)
            return

        interrupt = run.interrupts.get(interrupt_id)
        if not interrupt or interrupt.status != "OPEN":
            yield NoticeEvent(level="info", message="Interrupt already resolved")
            return

        if canonical_action_type == APPROVE_ACTION:
            input_data = {"approved": True}
        elif canonical_action_type == REJECT_ACTION:
            input_data = {"approved": False}
        elif canonical_action_type == SUBMIT_ACTION:
            try:
                input_data = self._input_from_payload(payload)
            except ValueError as exc:
                yield ErrorEvent(message=str(exc), allow_retry=False)
                return
        elif canonical_action_type == CANCEL_ACTION:
            yield ErrorEvent(message="interrupt cancel is not supported", allow_retry=False)
            return
        else:
            yield ErrorEvent(message="unsupported action", allow_retry=False)
            return

        idempotency = context.idempotency
        scope = "chatkit_action"
        idempotency_key = payload.get("idempotency_key") or payload.get("action_id")
        if not idempotency_key:
            idempotency_key = f"{run_id}:{interrupt_id}:{canonical_action_type}"
        if idempotency:
            started = await idempotency.start(idempotency_key, scope, tenant_id=context.tenant_id)
            if not started:
                yield NoticeEvent(level="info", message="Action already processed")
                return

        files = payload.get("files")
        try:
            run = await context.service.resume_interrupt(
                run,
                interrupt_id,
                input_data,
                files,
                tenant_id=context.tenant_id,
            )
        except Exception as exc:
            if idempotency:
                await idempotency.fail(idempotency_key, scope, {"error": str(exc)}, tenant_id=context.tenant_id)
            yield ErrorEvent(message=str(exc), allow_retry=True)
            return

        await self._run_store_save(context, run)
        if idempotency:
            await idempotency.complete(
                idempotency_key,
                scope,
                {"run_id": run.id, "status": run.status},
                tenant_id=context.tenant_id,
            )
        async for event in self._emit_run_events(run, thread, context, reuse_last=True):
            yield event

    async def _resolve_workflow(
        self,
        thread: ThreadMetadata,
        context: ChatKitContext,
    ) -> Optional[tuple[str, Optional[str]]]:
        metadata = thread.metadata or {}
        workflow_id = metadata.get("workflow_id")
        workflow_version_id = metadata.get("workflow_version_id")

        request_metadata = context.request_metadata or {}
        if not workflow_id and request_metadata.get("workflow_id"):
            workflow_id = request_metadata.get("workflow_id")
            workflow_version_id = request_metadata.get("workflow_version_id")
            thread.metadata["workflow_id"] = workflow_id
            if workflow_version_id:
                thread.metadata["workflow_version_id"] = workflow_version_id
            await self.store.save_thread(thread, context=context)

        if not workflow_id:
            return None

        return str(workflow_id), str(workflow_version_id) if workflow_version_id else None

    async def _emit_run_events(
        self,
        run: Run,
        thread: ThreadMetadata,
        context: ChatKitContext,
        reuse_last: bool,
    ) -> AsyncIterator[ThreadStreamEvent]:
        after_id = thread.metadata.get("last_event_id") if reuse_last else None
        events = context.service.store.list_events(run.id, after_id)

        message_buffer: List[str] = []
        last_event_id: Optional[str] = None

        for event in events:
            last_event_id = event.id
            if event.type == "message_generated":
                text = event.payload.get("text") if event.payload else None
                if text:
                    message_buffer.append(text)
                continue

            if message_buffer:
                yield self._assistant_message(thread, context, "".join(message_buffer))
                message_buffer = []

            if event.type == "run_waiting_for_input":
                for interrupt in run.interrupts.values():
                    if interrupt.status == "OPEN":
                        if interrupt.prompt:
                            yield self._assistant_message(thread, context, interrupt.prompt)
                        yield ThreadItemDoneEvent(
                            item=self._widget_item(thread, context, interrupt, run.id)
                        )
                continue

            progress_text = self._progress_text(event.type, event.node_id, event.payload)
            if progress_text:
                yield ProgressUpdateEvent(text=progress_text)

            if event.type == "run_completed":
                yield self._assistant_message(thread, context, self._completion_text(run))
            elif event.type == "run_failed":
                yield self._assistant_message(thread, context, self._failure_text(event.payload, run))

        if message_buffer:
            yield self._assistant_message(thread, context, "".join(message_buffer))

        if last_event_id:
            thread.metadata["last_event_id"] = last_event_id
            await self.store.save_thread(thread, context=context)

    def _assistant_message(self, thread: ThreadMetadata, context: ChatKitContext, text: str) -> ThreadItemDoneEvent:
        item = AssistantMessageItem(
            id=self.store.generate_item_id("message", thread, context),
            thread_id=thread.id,
            created_at=datetime.now(),
            content=[AssistantMessageContent(text=text)],
        )
        return ThreadItemDoneEvent(item=item)

    def _widget_item(
        self,
        thread: ThreadMetadata,
        context: ChatKitContext,
        interrupt: Interrupt,
        run_id: str,
    ) -> WidgetItem:
        widget = approval_widget(interrupt, run_id) if interrupt.type == "approval" else interaction_widget(interrupt, run_id)
        return WidgetItem(
            id=self.store.generate_item_id("message", thread, context),
            thread_id=thread.id,
            created_at=datetime.now(),
            widget=widget,
        )

    @staticmethod
    def _progress_text(event_type: str, node_id: Optional[str], payload: Optional[Dict[str, Any]]) -> Optional[str]:
        if event_type == "run_started":
            return "Run started"
        if event_type == "run_completed":
            return "Run completed"
        if event_type == "run_failed":
            return "Run failed"
        if event_type == "run_cancelled":
            return "Run cancelled"
        if event_type == "node_started" and node_id:
            return f"Node {node_id} started"
        if event_type == "node_completed" and node_id:
            return f"Node {node_id} completed"
        if event_type == "node_failed" and node_id:
            reason = payload.get("error") if payload else None
            return f"Node {node_id} failed" + (f": {reason}" if reason else "")
        if event_type == "node_retry" and node_id:
            attempt = payload.get("attempt") if payload else None
            reason = payload.get("error") if payload else None
            base = f"Node {node_id} retrying"
            if attempt:
                base += f" (attempt {attempt})"
            if reason:
                base += f": {reason}"
            return base
        return None

    @staticmethod
    def _completion_text(run: Run) -> str:
        if run.outputs is None:
            return "Workflow completed."
        try:
            output = json.dumps(run.outputs, indent=2, ensure_ascii=False)
        except Exception:
            output = str(run.outputs)
        return f"Workflow completed.\n\nOutput:\n{output}"

    @staticmethod
    def _failure_text(payload: Optional[Dict[str, Any]], run: Optional[Run] = None) -> str:
        if payload:
            return f"Run failed: {payload}"
        if run:
            errors = [nr.last_error for nr in run.node_runs.values() if nr.last_error]
            if errors:
                return f"Run failed: {errors[-1]}"
        return "Run failed."

    @staticmethod
    def _inputs_from_message(message: UserMessageItem) -> Dict[str, Any]:
        text = WorkflowChatKitServer._message_text(message)
        if not text:
            return {}
        trimmed = text.strip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            try:
                parsed = json.loads(trimmed)
                if isinstance(parsed, dict):
                    return parsed
                return {"items": parsed}
            except Exception:
                return {"message": text}
        return {"message": text}

    @staticmethod
    def _input_from_message(message: UserMessageItem) -> Dict[str, Any]:
        text = WorkflowChatKitServer._message_text(message)
        return {"message": text} if text else {}

    @staticmethod
    def _input_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        return normalize_custom_action_payload(payload)

    @staticmethod
    def _files_from_message(message: UserMessageItem) -> List[Dict[str, Any]]:
        files = []
        for attachment in message.attachments:
            files.append(
                {
                    "attachment_id": attachment.id,
                    "name": attachment.name,
                    "mime_type": attachment.mime_type,
                }
            )
        return files

    @staticmethod
    def _message_text(message: UserMessageItem) -> str:
        parts: List[str] = []
        for content in message.content:
            if getattr(content, "type", None) == "input_text":
                parts.append(content.text)
            elif getattr(content, "type", None) == "input_tag":
                parts.append(content.text)
        return " ".join(part for part in parts if part).strip()

    @staticmethod
    def _select_interrupt(run: Run) -> Optional[Interrupt]:
        for interrupt in run.interrupts.values():
            if interrupt.status == "OPEN":
                return interrupt
        return None

    @staticmethod
    async def _await_if_needed(value: Any) -> Any:
        if isawaitable(value):
            return await value
        return value

    async def _run_store_get(self, context: ChatKitContext, run_id: str) -> Optional[Run]:
        return await self._await_if_needed(context.run_store.get(run_id, tenant_id=context.tenant_id))

    async def _run_store_save(self, context: ChatKitContext, run: Run) -> None:
        await self._await_if_needed(context.run_store.save(run, tenant_id=context.tenant_id))
