from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from chatkit.store import AttachmentStore, NotFoundError, Store
from chatkit.types import (
    Attachment,
    AttachmentCreateParams,
    FileAttachment,
    Page,
    ThreadItem,
    ThreadMetadata,
)


@dataclass
class InMemoryChatKitStore(Store):
    threads: Dict[tuple[str, str], ThreadMetadata] = field(default_factory=dict)
    items: Dict[tuple[str, str], List[ThreadItem]] = field(default_factory=dict)
    attachments: Dict[tuple[str, str], Attachment] = field(default_factory=dict)

    @staticmethod
    def _tenant_id(context) -> str:
        tenant_id = getattr(context, "tenant_id", None)
        if isinstance(tenant_id, str) and tenant_id:
            return tenant_id
        raise RuntimeError("tenant_id is required in ChatKit context")

    async def load_thread(self, thread_id: str, context) -> ThreadMetadata:
        tenant_id = self._tenant_id(context)
        thread = self.threads.get((tenant_id, thread_id))
        if not thread:
            raise NotFoundError(f"thread {thread_id} not found")
        return thread

    async def save_thread(self, thread: ThreadMetadata, context) -> None:
        tenant_id = self._tenant_id(context)
        self.threads[(tenant_id, thread.id)] = thread

    async def load_thread_items(
        self,
        thread_id: str,
        after: Optional[str],
        limit: int,
        order: str,
        context,
    ) -> Page[ThreadItem]:
        tenant_id = self._tenant_id(context)
        items = list(self.items.get((tenant_id, thread_id), []))
        items.sort(key=lambda item: item.created_at, reverse=(order == "desc"))

        if after:
            try:
                after_index = next(i for i, item in enumerate(items) if item.id == after)
                items = items[after_index + 1 :]
            except StopIteration:
                items = []

        page_items = items[:limit]
        has_more = len(items) > limit
        after_id = page_items[-1].id if has_more and page_items else None
        return Page(data=page_items, has_more=has_more, after=after_id)

    async def save_attachment(self, attachment: Attachment, context) -> None:
        tenant_id = self._tenant_id(context)
        self.attachments[(tenant_id, attachment.id)] = attachment

    async def load_attachment(self, attachment_id: str, context) -> Attachment:
        tenant_id = self._tenant_id(context)
        attachment = self.attachments.get((tenant_id, attachment_id))
        if not attachment:
            raise NotFoundError(f"attachment {attachment_id} not found")
        return attachment

    async def delete_attachment(self, attachment_id: str, context) -> None:
        tenant_id = self._tenant_id(context)
        self.attachments.pop((tenant_id, attachment_id), None)

    async def load_threads(self, limit: int, after: Optional[str], order: str, context) -> Page[ThreadMetadata]:
        tenant_id = self._tenant_id(context)
        threads = [thread for (scope_tenant, _), thread in self.threads.items() if scope_tenant == tenant_id]
        threads.sort(key=lambda thread: thread.created_at, reverse=(order == "desc"))

        if after:
            try:
                after_index = next(i for i, thread in enumerate(threads) if thread.id == after)
                threads = threads[after_index + 1 :]
            except StopIteration:
                threads = []

        page_threads = threads[:limit]
        has_more = len(threads) > limit
        after_id = page_threads[-1].id if has_more and page_threads else None
        return Page(data=page_threads, has_more=has_more, after=after_id)

    async def add_thread_item(self, thread_id: str, item: ThreadItem, context) -> None:
        tenant_id = self._tenant_id(context)
        self.items.setdefault((tenant_id, thread_id), []).append(item)

    async def save_item(self, thread_id: str, item: ThreadItem, context) -> None:
        tenant_id = self._tenant_id(context)
        items = self.items.setdefault((tenant_id, thread_id), [])
        for idx, existing in enumerate(items):
            if existing.id == item.id:
                items[idx] = item
                return
        items.append(item)

    async def load_item(self, thread_id: str, item_id: str, context) -> ThreadItem:
        tenant_id = self._tenant_id(context)
        for item in self.items.get((tenant_id, thread_id), []):
            if item.id == item_id:
                return item
        raise NotFoundError(f"item {item_id} not found")

    async def delete_thread(self, thread_id: str, context) -> None:
        tenant_id = self._tenant_id(context)
        self.threads.pop((tenant_id, thread_id), None)
        self.items.pop((tenant_id, thread_id), None)

    async def delete_thread_item(self, thread_id: str, item_id: str, context) -> None:
        tenant_id = self._tenant_id(context)
        key = (tenant_id, thread_id)
        items = self.items.get(key, [])
        self.items[key] = [item for item in items if item.id != item_id]


@dataclass
class InMemoryAttachmentStore(AttachmentStore):
    attachments: Dict[tuple[str, str], Attachment]

    @staticmethod
    def _tenant_id(context) -> str:
        tenant_id = getattr(context, "tenant_id", None)
        if isinstance(tenant_id, str) and tenant_id:
            return tenant_id
        raise RuntimeError("tenant_id is required in ChatKit context")

    async def create_attachment(self, input: AttachmentCreateParams, context) -> Attachment:
        tenant_id = self._tenant_id(context)
        attachment_id = self.generate_attachment_id(input.mime_type, context)
        attachment = FileAttachment(
            id=attachment_id,
            name=input.name,
            mime_type=input.mime_type,
            upload_descriptor=None,
            thread_id=None,
            metadata={"size": input.size, "created_at": datetime.utcnow().isoformat()},
        )
        self.attachments[(tenant_id, attachment_id)] = attachment
        return attachment

    async def delete_attachment(self, attachment_id: str, context) -> None:
        tenant_id = self._tenant_id(context)
        self.attachments.pop((tenant_id, attachment_id), None)
