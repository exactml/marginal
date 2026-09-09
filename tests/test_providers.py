from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import openai
import pytest
from pydantic import BaseModel

from marginal.config import ModelSpec
from marginal.providers import (
    MissingCredentialsError,
    ProviderAPIError,
    ProviderResponseError,
    UnknownProviderError,
    get_provider,
)
from marginal.providers.anthropic import AnthropicProvider
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


async def test_anthropic_generate_structured_raises_without_tool_use():
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="not a tool call")]
    )
    provider = _anthropic_provider(client)

    with pytest.raises(ProviderResponseError):
        await provider.generate_structured("review this", Verdict)


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


async def test_openai_generate_structured_raises_on_empty_content():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
    )
    provider = _openai_provider(client)

    with pytest.raises(ProviderResponseError):
        await provider.generate_structured("review this", Verdict)


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
