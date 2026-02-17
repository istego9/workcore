from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import asyncpg
from minio import Minio

from chatkit.store import AttachmentStore
from chatkit.types import Attachment, AttachmentUploadDescriptor, FileAttachment


@dataclass
class MinioAttachmentStore(AttachmentStore):
    pool: asyncpg.Pool
    client: Minio
    bucket: str
    prefix: str
    upload_expires_seconds: int = 3600

    async def create_attachment(self, input, context) -> Attachment:
        attachment_id = self.generate_attachment_id(input.mime_type, context)
        object_key = f"{self.prefix}/{attachment_id}/{input.name}"
        url = self.client.presigned_put_object(
            self.bucket,
            object_key,
            expires=timedelta(seconds=self.upload_expires_seconds),
        )
        descriptor = AttachmentUploadDescriptor(url=url, method="PUT", headers={})
        return FileAttachment(
            id=attachment_id,
            name=input.name,
            mime_type=input.mime_type,
            upload_descriptor=descriptor,
            thread_id=None,
            metadata={"object_key": object_key, "size": input.size},
        )

    async def delete_attachment(self, attachment_id: str, context) -> None:
        tenant_id = getattr(context, "tenant_id", None)
        if not isinstance(tenant_id, str) or not tenant_id:
            raise RuntimeError("tenant_id is required in ChatKit context")
        row = await self.pool.fetchrow(
            "select attachment from chatkit_attachments where tenant_id = $1 and id = $2",
            tenant_id,
            attachment_id,
        )
        if not row:
            return
        attachment = row["attachment"]
        metadata = attachment.get("metadata") if isinstance(attachment, dict) else None
        object_key = metadata.get("object_key") if isinstance(metadata, dict) else None
        if object_key:
            self.client.remove_object(self.bucket, object_key)
