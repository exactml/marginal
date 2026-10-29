"""`ModelProvider` for a model served by Ollama or another OpenAI-compatible server."""

from __future__ import annotations

import openai

from marginal.providers.openai import OpenAIProvider

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"


class OllamaProvider(OpenAIProvider):
    """`ModelProvider` for a model served by Ollama (or another OpenAI-compatible
    local server such as vLLM), needing no API key. Ollama speaks the OpenAI
    API, so only the client differs."""

    _name = "ollama"

    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        client: openai.AsyncOpenAI | None = None,
    ) -> None:
        # The SDK refuses an empty key and would otherwise fall back to
        # OPENAI_API_KEY, sending a real cloud key to the local server.
        super().__init__(
            model,
            client=client
            or openai.AsyncOpenAI(api_key="ollama", base_url=base_url or DEFAULT_OLLAMA_BASE_URL),
        )
