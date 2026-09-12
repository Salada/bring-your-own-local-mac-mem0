"""Add Google Gen AI HTTP options missing from Mem0 2.0.20's Gemini adapter."""

from __future__ import annotations

import os
from typing import Any, Optional

from google import genai
from google.genai import types
from mem0.configs.llms.gemini import GeminiConfig
from mem0.llms.gemini import GeminiLLM
from mem0.utils.factory import LlmFactory


class GeminiHttpConfig(GeminiConfig):
    """Gemini configuration with client-level base URL and arbitrary headers."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        http_headers: Optional[dict[str, str]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if base_url is not None and not isinstance(base_url, str):
            raise TypeError("base_url must be a string")
        if http_headers is not None and (
            not isinstance(http_headers, dict)
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in http_headers.items())
        ):
            raise TypeError("http_headers must contain string names and values")
        self.base_url = base_url
        self.http_headers = dict(http_headers or {})


class GeminiHttpLLM(GeminiLLM):
    """Mem0 Gemini provider that forwards supported Google Gen AI HTTP options."""

    def __init__(self, config: Optional[GeminiHttpConfig | dict[str, Any]] = None) -> None:
        if isinstance(config, dict):
            config = GeminiHttpConfig(**config)
        elif config is None:
            config = GeminiHttpConfig()
        super().__init__(config)

        if not config.base_url and not config.http_headers:
            return

        previous_client = self.client
        http_options = types.HttpOptions(base_url=config.base_url, headers=config.http_headers or None)
        if config.vertexai:
            self.client = genai.Client(
                vertexai=True,
                project=config.project,
                location=config.location,
                http_options=http_options,
            )
        else:
            self.client = genai.Client(api_key=config.api_key or os.getenv("GOOGLE_API_KEY"), http_options=http_options)
        previous_client.close()


def register_gemini_http_compat() -> None:
    """Keep the public provider name while extending its pinned implementation."""
    LlmFactory.register_provider("gemini", "gemini_http.GeminiHttpLLM", GeminiHttpConfig)
