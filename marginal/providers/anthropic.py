"""`ModelProvider` backed by the Anthropic Messages API."""

from __future__ import annotations

from collections.abc import AsyncIterator

import anthropic
from pydantic import BaseModel, ValidationError

from marginal.providers.credentials import require_env
from marginal.providers.errors import ProviderAPIError, ProviderResponseError

DEFAULT_MAX_TOKENS = 4096
_STRUCTURED_OUTPUT_TOOL = "emit_structured_output"


def _find_tool_input(response: object, tool_name: str) -> dict | None:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return block.input
    return None


class AnthropicProvider:
    """`ModelProvider` for a single Claude model."""

    def __init__(self, model: str, *, client: anthropic.AsyncAnthropic | None = None) -> None:
        self._model = model
        self._client = client or anthropic.AsyncAnthropic(
            api_key=require_env("ANTHROPIC_API_KEY", provider="anthropic")
        )

    async def generate(self, prompt: str, **kwargs: object) -> str:
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=kwargs.pop("max_tokens", DEFAULT_MAX_TOKENS),
                messages=[{"role": "user", "content": prompt}],
                **kwargs,
            )
        except anthropic.APIError as exc:
            raise ProviderAPIError("anthropic", str(exc)) from exc
        return "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )

    async def generate_structured(
        self, prompt: str, schema: type[BaseModel], **kwargs: object
    ) -> BaseModel:
        max_tokens = kwargs.pop("max_tokens", DEFAULT_MAX_TOKENS)
        validation_error: ValidationError | None = None
        for _ in range(2):
            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=max_tokens,
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
            except anthropic.APIError as exc:
                raise ProviderAPIError("anthropic", str(exc)) from exc
            tool_input = _find_tool_input(response, _STRUCTURED_OUTPUT_TOOL)
            if tool_input is None:
                raise ProviderResponseError(
                    f"anthropic provider did not return the expected "
                    f"{_STRUCTURED_OUTPUT_TOOL!r} tool call"
                )
            try:
                return schema.model_validate(tool_input)
            except ValidationError as exc:
                validation_error = exc
        raise ProviderResponseError(
            f"anthropic structured output failed schema validation after retrying once: "
            f"{validation_error}"
        ) from validation_error

    async def stream(self, prompt: str, **kwargs: object) -> AsyncIterator[str]:
        try:
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
        except anthropic.APIError as exc:
            raise ProviderAPIError("anthropic", str(exc)) from exc
