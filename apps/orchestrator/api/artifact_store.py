from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ArtifactStoreError(RuntimeError):
    pass


class ArtifactNotFoundError(ArtifactStoreError):
    pass


class ArtifactAccessDeniedError(ArtifactStoreError):
    pass


class ArtifactExpiredError(ArtifactStoreError):
    pass


@dataclass
class ArtifactRecord:
    artifact_ref: str
    tenant_id: str
    mime_type: Optional[str]
    content: Any
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    expires_at: Optional[datetime] = None


class InMemoryArtifactStore:
    def __init__(self, tenant_id: str = "local") -> None:
        self.tenant_id = tenant_id
        self.artifacts: Dict[str, ArtifactRecord] = {}

    def put(
        self,
        artifact_ref: str,
        content: Any,
        *,
        tenant_id: Optional[str] = None,
        mime_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expires_at: Optional[datetime] = None,
    ) -> ArtifactRecord:
        tenant = tenant_id or self.tenant_id
        record = ArtifactRecord(
            artifact_ref=artifact_ref,
            tenant_id=tenant,
            mime_type=mime_type,
            content=content,
            metadata=dict(metadata or {}),
            expires_at=expires_at,
        )
        self.artifacts[artifact_ref] = record
        return record

    async def read(self, artifact_ref: str, *, tenant_id: Optional[str] = None) -> ArtifactRecord:
        ref = artifact_ref.strip() if isinstance(artifact_ref, str) else ""
        if not ref:
            raise ArtifactNotFoundError("artifact not found")
        record = self.artifacts.get(ref)
        if record is None:
            raise ArtifactNotFoundError("artifact not found")
        tenant = tenant_id or self.tenant_id
        if record.tenant_id != tenant:
            raise ArtifactAccessDeniedError("artifact access denied")
        if record.expires_at and record.expires_at <= _now():
            raise ArtifactExpiredError("artifact expired")
        return record

    async def close(self) -> None:
        return None


async def create_artifact_store() -> InMemoryArtifactStore:
    return InMemoryArtifactStore()
