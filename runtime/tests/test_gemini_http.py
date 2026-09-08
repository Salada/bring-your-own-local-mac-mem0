import unittest
from unittest import mock

from mem0.utils.factory import LlmFactory

from gemini_http import GeminiHttpConfig, register_gemini_http_compat


class GeminiHttpTest(unittest.TestCase):
    def test_registers_compatibility_adapter_under_standard_provider_name(self):
        original = LlmFactory.provider_to_class["gemini"]
        self.addCleanup(LlmFactory.provider_to_class.__setitem__, "gemini", original)

        register_gemini_http_compat()

        self.assertEqual(
            LlmFactory.provider_to_class["gemini"],
            ("gemini_http.GeminiHttpLLM", GeminiHttpConfig),
        )

    def test_vertex_client_receives_base_url_and_arbitrary_headers(self):
        original = LlmFactory.provider_to_class["gemini"]
        self.addCleanup(LlmFactory.provider_to_class.__setitem__, "gemini", original)
        register_gemini_http_compat()
        clients = [mock.Mock(), mock.Mock()]
        with mock.patch("gemini_http.genai.Client", side_effect=clients) as client:
            llm = LlmFactory.create(
                "gemini",
                config={
                    "model": "gemini-test",
                    "vertexai": True,
                    "project": "example-project",
                    "location": "us-central1",
                    "base_url": "https://gateway.example.test",
                    "http_headers": {
                        "Authorization": "example-value",
                        "X-Tenant": "example-team",
                    },
                },
            )

        self.assertIs(llm.client, clients[1])
        clients[0].close.assert_called_once_with()
        kwargs = client.call_args_list[1].kwargs
        self.assertTrue(kwargs["vertexai"])
        self.assertEqual(kwargs["project"], "example-project")
        self.assertEqual(kwargs["location"], "us-central1")
        self.assertEqual(kwargs["http_options"].base_url, "https://gateway.example.test")
        self.assertEqual(
            kwargs["http_options"].headers,
            {"Authorization": "example-value", "X-Tenant": "example-team"},
        )

    def test_rejects_non_string_header_values(self):
        with self.assertRaisesRegex(TypeError, "string names and values"):
            GeminiHttpConfig(http_headers={"X-Retry": 3})
