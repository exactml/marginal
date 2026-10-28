"""`ModelProvider`s backed by the OpenAI Chat Completions API or a compatible server."""

from __future__ import annotations

from collections.abc import AsyncIterator

import openai
from pydantic import BaseModel

from marginal.providers.base import record_usage, retry_once_on_validation_error
from marginal.providers.credentials import require_env
from marginal.providers.errors import ProviderAPIError, ProviderResponseError

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"


def _record_usage(response: object) -> None:
    usage = getattr(response, "usage", None)
    record_usage(getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None))


class OpenAIProvider:
    """`ModelProvider` for a single OpenAI (or Codex) model."""

    _name = "openai"

    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        client: openai.AsyncOpenAI | None = None,
    ) -> None:
        self._model = model
        self._client = client or openai.AsyncOpenAI(
            api_key=require_env("OPENAI_API_KEY", provider="openai"), base_url=base_url
        )

    async def generate(self, prompt: str, **kwargs: object) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                **kwargs,
            )
        except openai.APIError as exc:
            raise ProviderAPIError(self._name, str(exc)) from exc
        _record_usage(response)
        return response.choices[0].message.content or ""

    async def generate_structured(
        self, prompt: str, schema: type[BaseModel], **kwargs: object
    ) -> BaseModel:
        async def attempt() -> BaseModel:
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema.__name__,
                            "schema": schema.model_json_schema(),
                            "strict": True,
                        },
                    },
                    **kwargs,
                )
            except openai.APIError as exc:
                raise ProviderAPIError(self._name, str(exc)) from exc
            _record_usage(response)
            content = response.choices[0].message.content
            if content is None:
                raise ProviderResponseError(
                    f"{self._name} provider returned no structured-output content"
                )
            return schema.model_validate_json(content)

        return await retry_once_on_validation_error(self._name, attempt)

    async def stream(self, prompt: str, **kwargs: object) -> AsyncIterator[str]:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                **kwargs,
            )
            async for chunk in response:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except openai.APIError as exc:
            raise ProviderAPIError(self._name, str(exc)) from exc


class OllamaProvider(OpenAIProvider):
    """`ModelProvider` for a model served by Ollama (or another OpenAI-compatible
    local server such as vLLM), needing no API key."""

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
