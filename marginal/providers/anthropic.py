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


# Anthropic's strict tool use compiles `input_schema` into a grammar and
# rejects the whole request with a 400 if the schema uses a keyword outside
# its supported subset. Pydantic still enforces these bounds locally when the
# response is validated, so dropping them from the wire schema only loses the
# server-side guarantee for that specific bound, not the check itself.
_UNSUPPORTED_STRICT_KEYWORDS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "maxItems",
    }
)


def _strict_input_schema(schema: type[BaseModel]) -> dict:
    """`schema`'s JSON schema, adapted to what strict tool use accepts."""
    return _adapt_node(schema.model_json_schema())


def _adapt_node(node: object) -> object:
    if isinstance(node, list):
        return [_adapt_node(item) for item in node]
    if not isinstance(node, dict):
        return node
    nullable_type = _nullable_type(node)
    if nullable_type is not None:
        return {"type": [nullable_type, "null"]}
    return {
        key: _adapt_node(value)
        for key, value in node.items()
        if key not in _UNSUPPORTED_STRICT_KEYWORDS
    }


def _nullable_type(node: dict) -> str | None:
    """The bare type of pydantic's `X | None` rendering, or None if `node` isn't one.

    Pydantic renders an optional field as `anyOf: [{type: X}, {type: "null"}]`;
    the single-type-array form `{"type": [X, "null"]}` is the one Anthropic's
    docs describe for a nullable field, so it's the safer shape to send.
    """
    branches = node.get("anyOf")
    if not isinstance(branches, list) or len(branches) != 2:
        return None
    types = [branch.get("type") for branch in branches if isinstance(branch, dict)]
    if len(types) != 2 or None in types or "null" not in types:
        return None
    return next(candidate for candidate in types if candidate != "null")


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
        input_schema = _strict_input_schema(schema)
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
                            "input_schema": input_schema,
                            "strict": True,
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
