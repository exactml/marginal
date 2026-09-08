"""The `ModelProvider` interface every concrete provider implements."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


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
