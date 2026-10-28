"""The `ModelProvider` interface every concrete provider implements."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextvars import ContextVar
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from marginal.providers.errors import ProviderResponseError


@runtime_checkable
class ModelProvider(Protocol):
    """A callable LLM backend, resolved from one `provider` value in `models:`."""

    async def generate(self, prompt: str, **kwargs: object) -> str:
        """Generate a single text completion for `prompt`."""
        ...

    async def generate_structured(
        self, prompt: str, schema: type[BaseModel], **kwargs: object
    ) -> BaseModel:
        """Generate a completion validated against `schema`."""
        ...

    # Declared without `async` on purpose: concrete implementations are async
    # generator functions (`async def ...: yield ...`), which return an
    # AsyncIterator directly when called rather than a coroutine to await.
    def stream(self, prompt: str, **kwargs: object) -> AsyncIterator[str]:
        """Stream a text completion for `prompt` as it's generated."""
        ...


async def retry_once_on_validation_error(
    provider: str, attempt: Callable[[], Awaitable[BaseModel]]
) -> BaseModel:
    """Await `attempt()`, calling it once more if its output fails schema validation.

    A second `ValidationError` becomes a `ProviderResponseError`; any other
    error from `attempt` propagates on the first try, unretried.
    """
    validation_error: ValidationError | None = None
    for _ in range(2):
        try:
            return await attempt()
        except ValidationError as exc:
            validation_error = exc
    raise ProviderResponseError(
        f"{provider} structured output failed schema validation after retrying once: "
        f"{validation_error}"
    ) from validation_error


# Tokens summed over every model call since the last `reset_usage()`. A count
# stays None once any call didn't report it (e.g. an Ollama server that omits
# usage), since a partial sum would understate the cost. Held in a context
# variable, so reviews in different threads or asyncio tasks keep their own
# totals; tasks a review starts share its dict, so their calls count too.
_usage: ContextVar[dict[str, int | None]] = ContextVar("marginal_usage")


def _totals() -> dict[str, int | None]:
    totals = _usage.get(None)
    if totals is None:
        totals = {"input_tokens": 0, "output_tokens": 0}
        _usage.set(totals)
    return totals


def reset_usage() -> None:
    _usage.set({"input_tokens": 0, "output_tokens": 0})


def record_usage(input_tokens: int | None, output_tokens: int | None) -> None:
    totals = _totals()
    for key, value in (("input_tokens", input_tokens), ("output_tokens", output_tokens)):
        total = totals[key]
        totals[key] = None if value is None or total is None else total + value


def usage() -> dict[str, int | None]:
    """`{"input_tokens": ..., "output_tokens": ...}` since the last `reset_usage()`."""
    return dict(_totals())
