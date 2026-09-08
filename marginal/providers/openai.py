"""`ModelProvider` backed by the OpenAI Chat Completions API."""

from __future__ import annotations

from collections.abc import AsyncIterator

import openai
from pydantic import BaseModel

from marginal.providers.credentials import require_env
from marginal.providers.errors import ProviderResponseError


class OpenAIProvider:
    """`ModelProvider` for a single OpenAI (or Codex) model."""

    def __init__(self, model: str, *, client: openai.AsyncOpenAI | None = None) -> None:
        self._model = model
        self._client = client or openai.AsyncOpenAI(
            api_key=require_env("OPENAI_API_KEY", provider="openai")
        )

    async def generate(self, prompt: str, **kwargs: object) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        return response.choices[0].message.content or ""

    async def generate_structured(
        self, prompt: str, schema: type[BaseModel], **kwargs: object
    ) -> BaseModel:
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
        content = response.choices[0].message.content
        if content is None:
            raise ProviderResponseError("openai provider returned no structured-output content")
        return schema.model_validate_json(content)

    async def stream(self, prompt: str, **kwargs: object) -> AsyncIterator[str]:
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
