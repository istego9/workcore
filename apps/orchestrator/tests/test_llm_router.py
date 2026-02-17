import os
import unittest
from unittest import mock

from openai import AzureOpenAI
from apps.orchestrator.llm_adapter import LLMBadSchemaOutputError, ResponsesLLMRouter
from apps.orchestrator.llm_adapter.responses_router import LLMUnavailableError


class ResponsesLLMRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_heuristic_cancel_intent(self):
        router = ResponsesLLMRouter(force_heuristic=True)
        decision = await router.route(
            message_text="Отмени текущий процесс",
            candidates=[],
            active_workflow_id="wf_active",
            confidence_threshold=0.6,
            switch_margin_threshold=0.2,
            context_summary="",
            locale="ru-RU",
        )
        self.assertEqual(decision.route_type, "CANCEL")
        self.assertEqual(decision.workflow_id, "wf_active")

    async def test_heuristic_disambiguate_when_no_signal(self):
        router = ResponsesLLMRouter(force_heuristic=True)
        decision = await router.route(
            message_text="что-нибудь сделай",
            candidates=[
                {"workflow_id": "wf_a", "name": "Card", "description": "", "tags": ["card"], "examples": []},
                {"workflow_id": "wf_b", "name": "Loan", "description": "", "tags": ["loan"], "examples": []},
            ],
            active_workflow_id=None,
            confidence_threshold=0.8,
            switch_margin_threshold=0.3,
            context_summary="",
            locale="ru-RU",
        )
        self.assertEqual(decision.route_type, "DISAMBIGUATE")
        self.assertTrue(decision.clarifying_question)

    async def test_schema_validation_rejects_invalid_payload(self):
        router = ResponsesLLMRouter(force_heuristic=True)
        with self.assertRaises(LLMBadSchemaOutputError):
            router._validate_payload({"route_type": "START_WORKFLOW"})

    async def test_azure_client_is_selected_when_endpoint_set(self):
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "",
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
                "AZURE_OPENAI_API_KEY": "azure_test_key",
                "AZURE_OPENAI_API_VERSION": "2025-01-01-preview",
            },
            clear=False,
        ):
            router = ResponsesLLMRouter(force_heuristic=False)
            self.assertIsInstance(router.client, AzureOpenAI)

    async def test_azure_mode_requires_api_version(self):
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "",
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
                "AZURE_OPENAI_API_KEY": "azure_test_key",
                "AZURE_OPENAI_API_VERSION": "",
            },
            clear=False,
        ):
            router = ResponsesLLMRouter(force_heuristic=False)
            with self.assertRaises(LLMUnavailableError):
                await router.route(
                    message_text="test",
                    candidates=[],
                    active_workflow_id=None,
                    confidence_threshold=0.6,
                    switch_margin_threshold=0.2,
                    context_summary="",
                    locale="en-US",
                )


if __name__ == "__main__":
    unittest.main()
