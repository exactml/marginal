from datetime import date

from marginal.providers.pricing import LAST_UPDATED, PRICES, SOURCES, price_for


def test_price_for_reads_the_provider_and_model_from_usage():
    price = price_for("anthropic:claude-opus-5-5")

    assert (price.input, price.output, price.cache_read) == (4.0, 20.0, 0.20)
    assert price.cache_write == {"5m": 5.0, "1h": 8.0}
    assert price_for("openai:gpt-5.6-sol").cache_write == {"30m": 5.0, "12h": 10.0}
    assert price_for("openai:gpt-5.5").cache_write == {}  # no write price listed


def test_unlisted_models_have_no_price():
    assert price_for("ollama:llama3") is None
    assert price_for("anthropic:claude-unknown") is None
    assert price_for("claude-opus-5-5") is None  # usage always names the provider


def test_every_listed_provider_has_a_source_and_the_date_is_real():
    assert set(PRICES) == set(SOURCES)
    assert date.fromisoformat(LAST_UPDATED) <= date.today()
