"""Model provider abstraction (BYOK).

Concrete providers (`anthropic.py`, `openai.py`) are not imported here —
`get_provider` imports each one lazily, on first use, so that installing
`marginal[anthropic]` doesn't also require the `openai` SDK to be present.
"""

from marginal.providers.base import ModelProvider
from marginal.providers.errors import (
    MissingCredentialsError,
    ProviderError,
    ProviderResponseError,
    UnknownProviderError,
)
from marginal.providers.factory import get_provider

__all__ = [
    "MissingCredentialsError",
    "ModelProvider",
    "ProviderError",
    "ProviderResponseError",
    "UnknownProviderError",
    "get_provider",
]
