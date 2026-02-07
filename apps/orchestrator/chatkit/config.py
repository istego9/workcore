from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from apps.orchestrator.runtime.env import get_env, load_env


@dataclass
class ChatKitConfig:
    database_url: str
    auth_token: Optional[str]
    object_endpoint: str
    object_access_key: str
    object_secret_key: str
    object_bucket: str
    object_secure: bool
    object_prefix: str
    upload_expires_seconds: int
    create_bucket: bool
    idempotency_ttl_seconds: int

    @classmethod
    def from_env(cls) -> "ChatKitConfig":
        load_env()
        database_url = get_env("CHATKIT_DATABASE_URL")
        if not database_url:
            raise RuntimeError("CHATKIT_DATABASE_URL is required")

        object_endpoint = get_env("CHATKIT_OBJECT_ENDPOINT")
        object_access_key = get_env("CHATKIT_OBJECT_ACCESS_KEY")
        object_secret_key = get_env("CHATKIT_OBJECT_SECRET_KEY")
        object_bucket = get_env("CHATKIT_OBJECT_BUCKET")
        if not object_endpoint or not object_access_key or not object_secret_key or not object_bucket:
            raise RuntimeError("CHATKIT object storage env vars are required")

        object_secure = get_env("CHATKIT_OBJECT_SECURE", "true").lower() in {"1", "true", "yes"}
        object_prefix = get_env("CHATKIT_OBJECT_PREFIX", "chatkit")
        upload_expires_seconds = int(get_env("CHATKIT_UPLOAD_EXPIRES_SECONDS", "3600"))
        create_bucket = get_env("CHATKIT_OBJECT_CREATE_BUCKET", "false").lower() in {"1", "true", "yes"}
        idempotency_ttl_seconds = int(get_env("CHATKIT_IDEMPOTENCY_TTL_SECONDS", "300"))

        return cls(
            database_url=database_url,
            auth_token=get_env("CHATKIT_AUTH_TOKEN"),
            object_endpoint=object_endpoint,
            object_access_key=object_access_key,
            object_secret_key=object_secret_key,
            object_bucket=object_bucket,
            object_secure=object_secure,
            object_prefix=object_prefix,
            upload_expires_seconds=upload_expires_seconds,
            create_bucket=create_bucket,
            idempotency_ttl_seconds=idempotency_ttl_seconds,
        )
