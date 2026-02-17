from __future__ import annotations

from dataclasses import dataclass
import json
from datetime import datetime
from typing import Any, Optional

import asyncpg

from chatkit.store import NotFoundError, Store
from chatkit.types import Attachment, Page, ThreadItem, ThreadMetadata
from pydantic import TypeAdapter

THREAD_ITEM_ADAPTER = TypeAdapter(ThreadItem)


@dataclass
class PostgresChatKitStore(Store):
    pool: asyncpg.Pool

    @staticmethod
    def _load_json(value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def _dump_json(payload: Any) -> str:
        def _default(value):
            if isinstance(value, datetime):
                return value.isoformat()
            return str(value)

        return json.dumps(payload, default=_default)

    @staticmethod
    def _tenant_id(context: Any) -> str:
        tenant_id = getattr(context, "tenant_id", None)
        if isinstance(tenant_id, str) and tenant_id:
            return tenant_id
        raise RuntimeError("tenant_id is required in ChatKit context")

    async def load_thread(self, thread_id: str, context) -> ThreadMetadata:
        tenant_id = self._tenant_id(context)
        row = await self.pool.fetchrow(
            """
            select id, title, status, metadata, created_at
            from chatkit_threads
            where tenant_id = $1 and id = $2
            """,
            tenant_id,
            thread_id,
        )
        if not row:
            raise NotFoundError(f"thread {thread_id} not found")
        status = self._load_json(row["status"])
        metadata = self._load_json(row["metadata"]) or {}
        return ThreadMetadata.model_validate(
            {
                "id": row["id"],
                "title": row["title"],
                "status": status,
                "metadata": metadata,
                "created_at": row["created_at"],
            }
        )

    async def save_thread(self, thread: ThreadMetadata, context) -> None:
        tenant_id = self._tenant_id(context)
        payload = thread.model_dump()
        await self.pool.execute(
            """
            insert into chatkit_threads (tenant_id, id, title, status, metadata, created_at, updated_at)
            values ($1, $2, $3, $4::jsonb, $5::jsonb, $6, now())
            on conflict (tenant_id, id) do update
              set title = excluded.title,
                  status = excluded.status,
                  metadata = excluded.metadata,
                  updated_at = now()
            """,
            tenant_id,
            thread.id,
            payload.get("title"),
            self._dump_json(payload.get("status")),
            self._dump_json(payload.get("metadata") or {}),
            payload.get("created_at"),
        )

    async def load_thread_items(
        self,
        thread_id: str,
        after: Optional[str],
        limit: int,
        order: str,
        context,
    ) -> Page[ThreadItem]:
        tenant_id = self._tenant_id(context)
        direction = "DESC" if order == "desc" else "ASC"
        params: list[Any] = [tenant_id, thread_id]
        clause = ""
        if after:
            after_seq = await self.pool.fetchval(
                "select seq from chatkit_items where tenant_id = $1 and id = $2 and thread_id = $3",
                tenant_id,
                after,
                thread_id,
            )
            if after_seq is None:
                return Page(data=[], has_more=False, after=None)
            op = "<" if direction == "DESC" else ">"
            clause = f"and seq {op} $3"
            params.append(after_seq)

        params.append(limit + 1)
        rows = await self.pool.fetch(
            f"""
            select item
            from chatkit_items
            where tenant_id = $1 and thread_id = $2 {clause}
            order by seq {direction}
            limit ${len(params)}
            """,
            *params,
        )

        items = [
            THREAD_ITEM_ADAPTER.validate_python(
                json.loads(row["item"]) if isinstance(row["item"], str) else row["item"]
            )
            for row in rows[:limit]
        ]
        has_more = len(rows) > limit
        after_id = items[-1].id if has_more and items else None
        return Page(data=items, has_more=has_more, after=after_id)

    async def save_attachment(self, attachment: Attachment, context) -> None:
        tenant_id = self._tenant_id(context)
        payload = attachment.model_dump()
        await self.pool.execute(
            """
            insert into chatkit_attachments (tenant_id, id, thread_id, attachment, created_at)
            values ($1, $2, $3, $4::jsonb, now())
            on conflict (tenant_id, id) do update
              set thread_id = excluded.thread_id,
                  attachment = excluded.attachment
            """,
            tenant_id,
            payload.get("id"),
            payload.get("thread_id"),
            self._dump_json(payload),
        )

    async def load_attachment(self, attachment_id: str, context) -> Attachment:
        tenant_id = self._tenant_id(context)
        row = await self.pool.fetchrow(
            "select attachment from chatkit_attachments where tenant_id = $1 and id = $2",
            tenant_id,
            attachment_id,
        )
        if not row:
            raise NotFoundError(f"attachment {attachment_id} not found")
        attachment_data = row["attachment"]
        if isinstance(attachment_data, str):
            attachment_data = json.loads(attachment_data)
        return Attachment.model_validate(attachment_data)

    async def delete_attachment(self, attachment_id: str, context) -> None:
        tenant_id = self._tenant_id(context)
        await self.pool.execute(
            "delete from chatkit_attachments where tenant_id = $1 and id = $2",
            tenant_id,
            attachment_id,
        )

    async def load_threads(
        self,
        limit: int,
        after: Optional[str],
        order: str,
        context,
    ) -> Page[ThreadMetadata]:
        tenant_id = self._tenant_id(context)
        direction = "DESC" if order == "desc" else "ASC"
        params: list[Any] = []
        clause = ""
        if after:
            after_seq = await self.pool.fetchval(
                "select seq from chatkit_threads where tenant_id = $1 and id = $2",
                tenant_id,
                after,
            )
            if after_seq is None:
                return Page(data=[], has_more=False, after=None)
            op = "<" if direction == "DESC" else ">"
            clause = f"and seq {op} $2"
            params.append(after_seq)

        params.insert(0, tenant_id)
        params.append(limit + 1)
        rows = await self.pool.fetch(
            f"""
            select id, title, status, metadata, created_at
            from chatkit_threads
            where tenant_id = $1 {clause}
            order by seq {direction}
            limit ${len(params)}
            """,
            *params,
        )

        threads = []
        for row in rows[:limit]:
            threads.append(
                ThreadMetadata.model_validate(
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "status": self._load_json(row["status"]),
                        "metadata": self._load_json(row["metadata"]) or {},
                        "created_at": row["created_at"],
                    }
                )
            )
        has_more = len(rows) > limit
        after_id = threads[-1].id if has_more and threads else None
        return Page(data=threads, has_more=has_more, after=after_id)

    async def add_thread_item(self, thread_id: str, item: ThreadItem, context) -> None:
        tenant_id = self._tenant_id(context)
        payload = item.model_dump()
        await self.pool.execute(
            """
            insert into chatkit_items (tenant_id, id, thread_id, type, item, created_at)
            values ($1, $2, $3, $4, $5::jsonb, $6)
            on conflict (tenant_id, id) do update
              set thread_id = excluded.thread_id,
                  type = excluded.type,
                  item = excluded.item
            """,
            tenant_id,
            payload.get("id"),
            thread_id,
            payload.get("type"),
            self._dump_json(payload),
            payload.get("created_at"),
        )

    async def save_item(self, thread_id: str, item: ThreadItem, context) -> None:
        await self.add_thread_item(thread_id, item, context)

    async def load_item(self, thread_id: str, item_id: str, context) -> ThreadItem:
        tenant_id = self._tenant_id(context)
        row = await self.pool.fetchrow(
            "select item from chatkit_items where tenant_id = $1 and id = $2 and thread_id = $3",
            tenant_id,
            item_id,
            thread_id,
        )
        if not row:
            raise NotFoundError(f"item {item_id} not found")
        item_data = row["item"]
        if isinstance(item_data, str):
            item_data = json.loads(item_data)
        return THREAD_ITEM_ADAPTER.validate_python(item_data)

    async def delete_thread(self, thread_id: str, context) -> None:
        tenant_id = self._tenant_id(context)
        await self.pool.execute(
            "delete from chatkit_threads where tenant_id = $1 and id = $2",
            tenant_id,
            thread_id,
        )

    async def delete_thread_item(self, thread_id: str, item_id: str, context) -> None:
        tenant_id = self._tenant_id(context)
        await self.pool.execute(
            "delete from chatkit_items where tenant_id = $1 and id = $2 and thread_id = $3",
            tenant_id,
            item_id,
            thread_id,
        )
