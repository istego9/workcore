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
    stt_model: str
    stt_api_key: Optional[str]
    stt_timeout_seconds: int
    stt_max_audio_bytes: int
    stt_allowed_media_types: tuple[str, ...]

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
        stt_model = get_env("CHATKIT_STT_MODEL", "gpt-4o-mini-transcribe")
        stt_api_key = get_env("CHATKIT_STT_API_KEY") or get_env("OPENAI_API_KEY")
        stt_timeout_seconds = int(get_env("CHATKIT_STT_TIMEOUT_SECONDS", "30"))
        stt_max_audio_bytes = int(get_env("CHATKIT_STT_MAX_AUDIO_BYTES", str(10 * 1024 * 1024)))
        stt_allowed_raw = get_env(
            "CHATKIT_STT_ALLOWED_MEDIA_TYPES",
            "audio/webm,audio/ogg,audio/mp4",
        )
        stt_allowed_media_types = tuple(
            item.strip().lower()
            for item in stt_allowed_raw.split(",")
            if item.strip()
        )

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
            stt_model=stt_model,
            stt_api_key=stt_api_key,
            stt_timeout_seconds=stt_timeout_seconds,
            stt_max_audio_bytes=stt_max_audio_bytes,
            stt_allowed_media_types=stt_allowed_media_types,
        )
