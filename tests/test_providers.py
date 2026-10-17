import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import openai
import pytest
from pydantic import BaseModel, Field

from marginal.cli.review import _FindingsResponse
from marginal.config import ModelSpec
from marginal.providers import (
    MissingCredentialsError,
    ProviderAPIError,
    ProviderResponseError,
    UnknownProviderError,
    get_provider,
)
from marginal.providers.anthropic import AnthropicProvider, _strict_input_schema
from marginal.providers.credentials import require_env
from marginal.providers.openai import OpenAIProvider


class Verdict(BaseModel):
    approved: bool
    reason: str


def _sdk_error(exc_cls: type[Exception], message: str) -> Exception:
    """Build an SDK exception instance without its real (heavier) constructor args."""
    error = exc_cls.__new__(exc_cls)
    Exception.__init__(error, message)
    return error


# -- credentials --------------------------------------------------------


def test_require_env_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("SOME_API_KEY", "secret")

    assert require_env("SOME_API_KEY", provider="acme") == "secret"


def test_require_env_raises_when_missing(monkeypatch):
    monkeypatch.delenv("SOME_API_KEY", raising=False)

    with pytest.raises(MissingCredentialsError, match="SOME_API_KEY"):
        require_env("SOME_API_KEY", provider="acme")


# -- factory --------------------------------------------------------------


def test_get_provider_rejects_unsupported_provider():
    spec = ModelSpec(provider="google", model="gemini")

    with pytest.raises(UnknownProviderError, match="google"):
        get_provider(spec)


def test_get_provider_reports_missing_anthropic_credential(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    spec = ModelSpec(provider="anthropic", model="claude-sonnet")

    with pytest.raises(MissingCredentialsError, match="ANTHROPIC_API_KEY"):
        get_provider(spec)


def test_get_provider_reports_missing_openai_credential(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    spec = ModelSpec(provider="openai", model="codex")

    with pytest.raises(MissingCredentialsError, match="OPENAI_API_KEY"):
        get_provider(spec)


def test_get_provider_resolves_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    spec = ModelSpec(provider="anthropic", model="claude-sonnet")

    provider = get_provider(spec)

    assert isinstance(provider, AnthropicProvider)


def test_get_provider_resolves_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    spec = ModelSpec(provider="openai", model="codex")

    provider = get_provider(spec)

    assert isinstance(provider, OpenAIProvider)


# -- AnthropicProvider ------------------------------------------------------


def _anthropic_provider(client):
    return AnthropicProvider("claude-sonnet", client=client)


async def test_anthropic_generate_joins_text_blocks():
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="hello "),
            SimpleNamespace(type="text", text="world"),
        ]
    )
    provider = _anthropic_provider(client)

    result = await provider.generate("say hi")

    assert result == "hello world"
    _, kwargs = client.messages.create.call_args
    assert kwargs["model"] == "claude-sonnet"
    assert kwargs["max_tokens"] == 4096
    assert kwargs["messages"] == [{"role": "user", "content": "say hi"}]


async def test_anthropic_generate_structured_validates_tool_input():
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                name="emit_structured_output",
                input={"approved": True, "reason": "looks good"},
            )
        ]
    )
    provider = _anthropic_provider(client)

    result = await provider.generate_structured("review this", Verdict)

    assert result == Verdict(approved=True, reason="looks good")


async def test_anthropic_generate_structured_requests_strict_tool_use():
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                name="emit_structured_output",
                input={"approved": True, "reason": "looks good"},
            )
        ]
    )
    provider = _anthropic_provider(client)

    await provider.generate_structured("review this", Verdict)

    _, kwargs = client.messages.create.call_args
    assert kwargs["tools"][0]["strict"] is True


class Scored(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    tags: list[str] = Field(max_length=3)
    note: int | None = None


async def test_anthropic_generate_structured_strips_keywords_strict_mode_rejects():
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                name="emit_structured_output",
                input={"score": 0.9, "tags": ["a"], "note": None},
            )
        ]
    )
    provider = _anthropic_provider(client)

    await provider.generate_structured("review this", Scored)

    _, kwargs = client.messages.create.call_args
    sent_schema = json.dumps(kwargs["tools"][0]["input_schema"])
    # Strict tool use rejects a request outright (400, before any generation)
    # if the schema uses any of these -- confirmed live in production.
    for forbidden in ("minimum", "maximum", "maxItems", "anyOf"):
        assert forbidden not in sent_schema, f"{forbidden!r} leaked into the strict schema"


async def test_anthropic_generate_structured_still_enforces_stripped_bounds_locally():
    """Stripping `minimum`/`maximum` from the wire schema must not stop
    pydantic from rejecting an out-of-bounds value in the response -- the
    server-side guarantee is gone, but the client-side check must stay."""
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                name="emit_structured_output",
                input={"score": 1.5, "tags": ["a"], "note": None},
            )
        ]
    )
    provider = _anthropic_provider(client)

    with pytest.raises(ProviderResponseError, match="failed schema validation"):
        await provider.generate_structured("review this", Scored)


async def test_anthropic_generate_structured_findings_response_schema_is_strict_compatible():
    """Regression test for the exact schema that broke production: strict
    tool use rejected `_FindingsResponse` outright because `Finding.confidence`
    carries `ge=0.0, le=1.0` and `_FindingsResponse.findings` carries a
    `max_length` -- both render as keywords strict mode doesn't support."""
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                name="emit_structured_output",
                input={"findings": []},
            )
        ]
    )
    provider = _anthropic_provider(client)

    await provider.generate_structured("review this", _FindingsResponse)

    _, kwargs = client.messages.create.call_args
    sent_schema = json.dumps(kwargs["tools"][0]["input_schema"])
    for forbidden in ("minimum", "maximum", "maxItems", "anyOf"):
        assert forbidden not in sent_schema, f"{forbidden!r} leaked into the strict schema"


class Unique(BaseModel):
    tags: set[str]


def test_strict_input_schema_strips_unique_items():
    schema = _strict_input_schema(Unique)

    assert "uniqueItems" not in json.dumps(schema)


class Pattern(BaseModel):
    code: str = Field(pattern=r"^[A-Z]+$")


def test_strict_input_schema_raises_on_an_unvetted_keyword():
    with pytest.raises(ValueError, match="pattern"):
        _strict_input_schema(Pattern)


async def test_anthropic_generate_structured_wraps_validation_error():
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                name="emit_structured_output",
                input={"parameter name": "CHANGELOG.md"},
            )
        ]
    )
    provider = _anthropic_provider(client)

    with pytest.raises(ProviderResponseError, match="failed schema validation"):
        await provider.generate_structured("review this", Verdict)


async def test_anthropic_generate_structured_raises_without_tool_use():
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="not a tool call")]
    )
    provider = _anthropic_provider(client)

    with pytest.raises(ProviderResponseError):
        await provider.generate_structured("review this", Verdict)

    assert client.messages.create.call_count == 1


def _anthropic_tool_response(tool_input: object) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name="emit_structured_output", input=tool_input)]
    )


async def test_anthropic_generate_structured_retries_once_after_validation_error():
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.side_effect = [
        _anthropic_tool_response({"approved": "not-a-bool"}),
        _anthropic_tool_response({"approved": True, "reason": "fixed on retry"}),
    ]
    provider = _anthropic_provider(client)

    result = await provider.generate_structured("review this", Verdict)

    assert result == Verdict(approved=True, reason="fixed on retry")
    assert client.messages.create.call_count == 2


async def test_anthropic_generate_structured_fails_after_two_invalid_attempts():
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.side_effect = [
        _anthropic_tool_response({"parameter name": "CHANGELOG.md"}),
        _anthropic_tool_response({"parameter name": "CHANGELOG.md"}),
    ]
    provider = _anthropic_provider(client)

    with pytest.raises(ProviderResponseError, match="after retrying once"):
        await provider.generate_structured("review this", Verdict)

    assert client.messages.create.call_count == 2


async def test_anthropic_stream_yields_only_text_deltas():
    events = [
        SimpleNamespace(type="message_start"),
        SimpleNamespace(
            type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="he")
        ),
        SimpleNamespace(
            type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="llo")
        ),
        SimpleNamespace(type="message_stop"),
    ]

    async def event_stream():
        for event in events:
            yield event

    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.return_value = event_stream()
    provider = _anthropic_provider(client)

    chunks = [chunk async for chunk in provider.stream("say hi")]

    assert chunks == ["he", "llo"]


async def test_anthropic_generate_wraps_sdk_api_error():
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.side_effect = _sdk_error(anthropic.APIError, "rate limited")
    provider = _anthropic_provider(client)

    with pytest.raises(ProviderAPIError, match="rate limited"):
        await provider.generate("say hi")


async def test_anthropic_generate_structured_wraps_sdk_api_error():
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.side_effect = _sdk_error(anthropic.APIError, "bad request")
    provider = _anthropic_provider(client)

    with pytest.raises(ProviderAPIError, match="bad request"):
        await provider.generate_structured("review this", Verdict)


async def test_anthropic_stream_wraps_sdk_api_error():
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.side_effect = _sdk_error(anthropic.APIError, "connection reset")
    provider = _anthropic_provider(client)

    with pytest.raises(ProviderAPIError, match="connection reset"):
        async for _ in provider.stream("say hi"):
            pass


async def test_anthropic_stream_wraps_sdk_api_error_mid_iteration():
    async def failing_stream():
        yield SimpleNamespace(
            type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="he")
        )
        raise _sdk_error(anthropic.APIError, "connection reset mid-stream")

    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.return_value = failing_stream()
    provider = _anthropic_provider(client)

    chunks = []
    with pytest.raises(ProviderAPIError, match="connection reset mid-stream"):
        async for chunk in provider.stream("say hi"):
            chunks.append(chunk)

    assert chunks == ["he"]


# -- OpenAIProvider -----------------------------------------------------


def _openai_provider(client):
    return OpenAIProvider("codex", client=client)


async def test_openai_generate_returns_message_content():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello world"))]
    )
    provider = _openai_provider(client)

    result = await provider.generate("say hi")

    assert result == "hello world"
    _, kwargs = client.chat.completions.create.call_args
    assert kwargs["model"] == "codex"
    assert kwargs["messages"] == [{"role": "user", "content": "say hi"}]


async def test_openai_generate_structured_parses_json_content():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"approved": false, "reason": "missing tests"}')
            )
        ]
    )
    provider = _openai_provider(client)

    result = await provider.generate_structured("review this", Verdict)

    assert result == Verdict(approved=False, reason="missing tests")


async def test_openai_generate_structured_wraps_validation_error():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content='{"parameter name": "CHANGELOG.md"}'))
        ]
    )
    provider = _openai_provider(client)

    with pytest.raises(ProviderResponseError, match="failed schema validation"):
        await provider.generate_structured("review this", Verdict)


async def test_openai_generate_structured_raises_on_empty_content():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
    )
    provider = _openai_provider(client)

    with pytest.raises(ProviderResponseError):
        await provider.generate_structured("review this", Verdict)

    assert client.chat.completions.create.call_count == 1


def _openai_content_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


async def test_openai_generate_structured_retries_once_after_validation_error():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
    client.chat.completions.create.side_effect = [
        _openai_content_response('{"approved": "not-a-bool"}'),
        _openai_content_response('{"approved": true, "reason": "fixed on retry"}'),
    ]
    provider = _openai_provider(client)

    result = await provider.generate_structured("review this", Verdict)

    assert result == Verdict(approved=True, reason="fixed on retry")
    assert client.chat.completions.create.call_count == 2


async def test_openai_generate_structured_fails_after_two_invalid_attempts():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
    client.chat.completions.create.side_effect = [
        _openai_content_response('{"parameter name": "CHANGELOG.md"}'),
        _openai_content_response('{"parameter name": "CHANGELOG.md"}'),
    ]
    provider = _openai_provider(client)

    with pytest.raises(ProviderResponseError, match="after retrying once"):
        await provider.generate_structured("review this", Verdict)

    assert client.chat.completions.create.call_count == 2


async def test_openai_stream_yields_only_non_empty_deltas():
    chunks_in = [
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="he"))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="llo"))]),
    ]

    async def chunk_stream():
        for chunk in chunks_in:
            yield chunk

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
    client.chat.completions.create.return_value = chunk_stream()
    provider = _openai_provider(client)

    chunks = [chunk async for chunk in provider.stream("say hi")]

    assert chunks == ["he", "llo"]


async def test_openai_generate_wraps_sdk_api_error():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
    client.chat.completions.create.side_effect = _sdk_error(openai.APIError, "rate limited")
    provider = _openai_provider(client)

    with pytest.raises(ProviderAPIError, match="rate limited"):
        await provider.generate("say hi")


async def test_openai_generate_structured_wraps_sdk_api_error():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
    client.chat.completions.create.side_effect = _sdk_error(openai.APIError, "bad request")
    provider = _openai_provider(client)

    with pytest.raises(ProviderAPIError, match="bad request"):
        await provider.generate_structured("review this", Verdict)


async def test_openai_stream_wraps_sdk_api_error():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
    client.chat.completions.create.side_effect = _sdk_error(openai.APIError, "connection reset")
    provider = _openai_provider(client)

    with pytest.raises(ProviderAPIError, match="connection reset"):
        async for _ in provider.stream("say hi"):
            pass


async def test_openai_stream_wraps_sdk_api_error_mid_iteration():
    async def failing_stream():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="he"))])
        raise _sdk_error(openai.APIError, "connection reset mid-stream")

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
    client.chat.completions.create.return_value = failing_stream()
    provider = _openai_provider(client)

    chunks = []
    with pytest.raises(ProviderAPIError, match="connection reset mid-stream"):
        async for chunk in provider.stream("say hi"):
            chunks.append(chunk)

    assert chunks == ["he"]
