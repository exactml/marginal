"""Model list prices, for working out what a review cost.

USD per million tokens, standard (non-batch) API rates, copied from each
provider's pricing page. Update `LAST_UPDATED` with every change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LAST_UPDATED = "2026-10-28"

SOURCES = {
    "anthropic": "https://platform.claude.com/docs/en/about-claude/pricing",
    "openai": "https://developers.openai.com/api/docs/pricing",
}


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens.

    `cache_read` is a cache hit. `cache_write` maps how long a write stays
    cached to its price; it's empty when writing to the cache costs nothing
    beyond `input`.
    """

    input: float
    output: float
    cache_read: float
    cache_write: dict[str, float] = field(default_factory=dict)


def _anthropic(
    input: float, output: float, cache_read: float, write_5m: float, write_1h: float
) -> ModelPrice:
    """Anthropic keeps a cache write for 5 minutes or 1 hour."""
    return ModelPrice(input, output, cache_read, {"5m": write_5m, "1h": write_1h})


def _openai(
    input: float,
    output: float,
    cache_read: float,
    write_30m: float | None = None,
    write_12h: float | None = None,
) -> ModelPrice:
    """OpenAI lists cache write prices (30 minutes, 12 hours) for some models only."""
    writes = {"30m": write_30m, "12h": write_12h}
    return ModelPrice(
        input, output, cache_read, {span: price for span, price in writes.items() if price}
    )


# shortcut: short-context rates only (Claude Haiku 5.5 prompts up to 100K
# tokens, OpenAI prompts under 272K); add the long-context tiers when a
# review's prompt can reach them.
PRICES: dict[str, dict[str, ModelPrice]] = {
    # input, output, cache read, 5m cache write, 1h cache write
    "anthropic": {
        "claude-fable-5-1": _anthropic(10.0, 50.0, 0.25, 12.50, 20.0),
        "claude-fable-5": _anthropic(10.0, 50.0, 1.0, 12.50, 20.0),
        "claude-opus-5-5": _anthropic(4.0, 20.0, 0.20, 5.0, 8.0),
        "claude-opus-5": _anthropic(5.0, 25.0, 0.50, 6.25, 10.0),
        "claude-opus-4-8": _anthropic(5.0, 25.0, 0.50, 6.25, 10.0),
        "claude-opus-4-7": _anthropic(5.0, 25.0, 0.50, 6.25, 10.0),
        "claude-opus-4-6": _anthropic(5.0, 25.0, 0.50, 6.25, 10.0),
        "claude-opus-4-5": _anthropic(5.0, 25.0, 0.50, 6.25, 10.0),
        "claude-sonnet-5-5": _anthropic(2.0, 10.0, 0.10, 2.50, 4.0),
        "claude-sonnet-5": _anthropic(2.0, 10.0, 0.20, 2.50, 4.0),
        "claude-sonnet-4-6": _anthropic(3.0, 15.0, 0.30, 3.75, 6.0),
        "claude-sonnet-4-5": _anthropic(3.0, 15.0, 0.30, 3.75, 6.0),
        "claude-haiku-5-5": _anthropic(0.10, 0.50, 0.01, 0.125, 0.20),
        "claude-haiku-4-5": _anthropic(1.0, 5.0, 0.10, 1.25, 2.0),
    },
    # input, output, cached input, 30m cache write, 12h cache write
    "openai": {
        "gpt-5.6-sol": _openai(4.0, 20.0, 0.40, 5.0, 10.0),
        "gpt-5.6-terra": _openai(2.0, 12.0, 0.20, 2.50, 5.0),
        "gpt-5.6-luna": _openai(0.20, 1.20, 0.02, 0.25, 0.50),
        "gpt-5.5": _openai(5.0, 30.0, 0.50),
        "gpt-5.4": _openai(2.50, 15.0, 0.25),
        "gpt-5.4-mini": _openai(0.75, 4.50, 0.075),
        "gpt-5.4-nano": _openai(0.20, 1.25, 0.02),
        "gpt-5.2": _openai(1.75, 14.0, 0.175),
        "gpt-5.1": _openai(1.25, 10.0, 0.125),
        "gpt-5": _openai(1.25, 10.0, 0.125),
        "gpt-5-mini": _openai(0.25, 2.0, 0.025),
        "gpt-5-nano": _openai(0.05, 0.40, 0.005),
        "gpt-4.1": _openai(2.0, 8.0, 0.50),
        "gpt-4.1-mini": _openai(0.40, 1.60, 0.10),
        "gpt-4.1-nano": _openai(0.10, 0.40, 0.025),
        "gpt-4o": _openai(2.50, 10.0, 1.25),
        "gpt-4o-mini": _openai(0.15, 0.60, 0.075),
    },
}


def price_for(model: str) -> ModelPrice | None:
    """The price of `"<provider>:<model id>"`, the form a review's `usage`
    reports, or None when it isn't listed (e.g. a local Ollama model)."""
    provider, _, model_id = model.partition(":")
    return PRICES.get(provider, {}).get(model_id)
