import os
import unittest
from types import SimpleNamespace
from unittest import mock

from apps.orchestrator.chatkit.config import ChatKitConfig
from apps.orchestrator.chatkit.service import _build_transcriber


class _AudioInput:
    def __init__(self, data: bytes, mime_type: str, media_type: str) -> None:
        self.data = data
        self.mime_type = mime_type
        self.media_type = media_type


def _chatkit_config(stt_api_key: str | None = "test_stt_key") -> ChatKitConfig:
    return ChatKitConfig(
        database_url="postgresql://localhost/test",
        auth_token=None,
        object_endpoint="localhost:9000",
        object_access_key="minio",
        object_secret_key="minio-secret",
        object_bucket="chatkit",
        object_secure=False,
        object_prefix="chatkit",
        upload_expires_seconds=3600,
        create_bucket=False,
        idempotency_ttl_seconds=300,
        stt_model="wf-stt",
        stt_api_key=stt_api_key,
        stt_timeout_seconds=30,
        stt_max_audio_bytes=1024 * 1024,
        stt_allowed_media_types=("audio/webm",),
    )


class ChatKitTranscriberProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_azure_transcriber_selected_when_endpoint_set(self):
        captured: dict[str, object] = {}

        class FakeAzureClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.audio = SimpleNamespace(
                    transcriptions=SimpleNamespace(
                        create=mock.AsyncMock(return_value={"text": "azure-ok"})
                    )
                )

        with mock.patch.dict(
            os.environ,
            {
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
                "AZURE_OPENAI_API_VERSION": "2025-01-01-preview",
            },
            clear=False,
        ):
            with mock.patch("openai.AsyncAzureOpenAI", new=FakeAzureClient):
                transcriber = _build_transcriber(_chatkit_config())
                self.assertIsNotNone(transcriber)
                text = await transcriber(
                    _AudioInput(
                        data=b"hello",
                        mime_type="audio/webm",
                        media_type="audio/webm",
                    ),
                    None,
                )
        self.assertEqual(text, "azure-ok")
        self.assertEqual(captured.get("azure_endpoint"), "https://example.openai.azure.com/")
        self.assertEqual(captured.get("api_version"), "2025-01-01-preview")

    async def test_azure_transcriber_fails_fast_without_api_version(self):
        with mock.patch.dict(
            os.environ,
            {
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
                "AZURE_OPENAI_API_VERSION": "",
            },
            clear=False,
        ):
            transcriber = _build_transcriber(_chatkit_config())
        self.assertIsNone(transcriber)


if __name__ == "__main__":
    unittest.main()
