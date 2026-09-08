"""Resolve a `ModelSpec` to a working `ModelProvider`."""

from __future__ import annotations

import importlib

from marginal.config.schema import ModelSpec
from marginal.providers.base import ModelProvider
from marginal.providers.errors import ProviderError, UnknownProviderError

# module:class per supported `provider` value. Modules are imported lazily
# (only once actually requested) so that e.g. installing `marginal[anthropic]`
# doesn't require the `openai` SDK to be present too.
_REGISTRY: dict[str, str] = {
    "anthropic": "marginal.providers.anthropic:AnthropicProvider",
    "openai": "marginal.providers.openai:OpenAIProvider",
}


def get_provider(spec: ModelSpec) -> ModelProvider:
    """Resolve `spec` to a `ModelProvider`, reading credentials from the environment.

    Raises `UnknownProviderError` if `spec.provider` has no registered
    implementation, or `MissingCredentialsError` if the provider's API key
    environment variable is not set.
    """
    try:
        target = _REGISTRY[spec.provider]
    except KeyError:
        raise UnknownProviderError(
            f"unsupported model provider {spec.provider!r} "
            f"(supported: {', '.join(sorted(_REGISTRY))})"
        ) from None

    module_path, class_name = target.split(":")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ProviderError(
            f"the {spec.provider!r} provider requires its SDK to be installed "
            f"(pip install 'marginal[{spec.provider}]')"
        ) from exc

    provider_cls = getattr(module, class_name)
    return provider_cls(spec.model)
