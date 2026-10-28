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


def _anthropic(input: float, output: float, cache_read: float) -> ModelPrice:
    # Anthropic charges 1.25x input for a 5-minute cache write, 2x for 1 hour.
    return ModelPrice(input, output, cache_read, {"5m": input * 1.25, "1h": input * 2})


# shortcut: short-context rates only (Claude Haiku 5.5 prompts up to 100K
# tokens, OpenAI prompts under 272K); add the long-context tiers when a
# review's prompt can reach them.
PRICES: dict[str, dict[str, ModelPrice]] = {
    "anthropic": {
        "claude-fable-5-1": _anthropic(10.0, 50.0, cache_read=0.25),
        "claude-fable-5": _anthropic(10.0, 50.0, cache_read=1.0),
        "claude-opus-5-5": _anthropic(4.0, 20.0, cache_read=0.20),
        "claude-opus-5": _anthropic(5.0, 25.0, cache_read=0.50),
        "claude-opus-4-8": _anthropic(5.0, 25.0, cache_read=0.50),
        "claude-opus-4-7": _anthropic(5.0, 25.0, cache_read=0.50),
        "claude-opus-4-6": _anthropic(5.0, 25.0, cache_read=0.50),
        "claude-opus-4-5": _anthropic(5.0, 25.0, cache_read=0.50),
        "claude-sonnet-5-5": _anthropic(2.0, 10.0, cache_read=0.10),
        "claude-sonnet-5": _anthropic(2.0, 10.0, cache_read=0.20),
        "claude-sonnet-4-6": _anthropic(3.0, 15.0, cache_read=0.30),
        "claude-sonnet-4-5": _anthropic(3.0, 15.0, cache_read=0.30),
        "claude-haiku-5-5": _anthropic(0.10, 0.50, cache_read=0.01),
        "claude-haiku-4-5": _anthropic(1.0, 5.0, cache_read=0.10),
    },
    "openai": {
        "gpt-5.6-sol": ModelPrice(4.0, 20.0, 0.40, {"30m": 5.0, "12h": 10.0}),
        "gpt-5.6-terra": ModelPrice(2.0, 12.0, 0.20, {"30m": 2.5, "12h": 5.0}),
        "gpt-5.6-luna": ModelPrice(0.20, 1.20, 0.02, {"30m": 0.25, "12h": 0.50}),
        "gpt-5.5": ModelPrice(5.0, 30.0, 0.50),
        "gpt-5.4": ModelPrice(2.50, 15.0, 0.25),
        "gpt-5.4-mini": ModelPrice(0.75, 4.50, 0.075),
        "gpt-5.4-nano": ModelPrice(0.20, 1.25, 0.02),
        "gpt-5.2": ModelPrice(1.75, 14.0, 0.175),
        "gpt-5.1": ModelPrice(1.25, 10.0, 0.125),
        "gpt-5": ModelPrice(1.25, 10.0, 0.125),
        "gpt-5-mini": ModelPrice(0.25, 2.0, 0.025),
        "gpt-5-nano": ModelPrice(0.05, 0.40, 0.005),
        "gpt-4.1": ModelPrice(2.0, 8.0, 0.50),
        "gpt-4.1-mini": ModelPrice(0.40, 1.60, 0.10),
        "gpt-4.1-nano": ModelPrice(0.10, 0.40, 0.025),
        "gpt-4o": ModelPrice(2.50, 10.0, 1.25),
        "gpt-4o-mini": ModelPrice(0.15, 0.60, 0.075),
    },
}


def price_for(model: str) -> ModelPrice | None:
    """The price of `"<provider>:<model id>"`, the form a review's `usage`
    reports, or None when it isn't listed (e.g. a local Ollama model)."""
    provider, _, model_id = model.partition(":")
    return PRICES.get(provider, {}).get(model_id)
