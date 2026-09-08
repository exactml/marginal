"""`ModelProvider` backed by the Anthropic Messages API."""

from __future__ import annotations

from collections.abc import AsyncIterator

import anthropic
from pydantic import BaseModel

from marginal.providers.credentials import require_env
from marginal.providers.errors import ProviderResponseError

DEFAULT_MAX_TOKENS = 4096
_STRUCTURED_OUTPUT_TOOL = "emit_structured_output"


class AnthropicProvider:
    """`ModelProvider` for a single Claude model."""

    def __init__(self, model: str, *, client: anthropic.AsyncAnthropic | None = None) -> None:
        self._model = model
        self._client = client or anthropic.AsyncAnthropic(
            api_key=require_env("ANTHROPIC_API_KEY", provider="anthropic")
        )

    async def generate(self, prompt: str, **kwargs: object) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=kwargs.pop("max_tokens", DEFAULT_MAX_TOKENS),
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        return "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )

    async def generate_structured(
        self, prompt: str, schema: type[BaseModel], **kwargs: object
    ) -> BaseModel:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=kwargs.pop("max_tokens", DEFAULT_MAX_TOKENS),
            messages=[{"role": "user", "content": prompt}],
            tools=[
                {
                    "name": _STRUCTURED_OUTPUT_TOOL,
                    "description": "Return the requested structured output.",
                    "input_schema": schema.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": _STRUCTURED_OUTPUT_TOOL},
            **kwargs,
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == _STRUCTURED_OUTPUT_TOOL:
                return schema.model_validate(block.input)
        raise ProviderResponseError(
            f"anthropic provider did not return the expected {_STRUCTURED_OUTPUT_TOOL!r} tool call"
        )

    async def stream(self, prompt: str, **kwargs: object) -> AsyncIterator[str]:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=kwargs.pop("max_tokens", DEFAULT_MAX_TOKENS),
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            **kwargs,
        )
        async for event in response:
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                yield event.delta.text
