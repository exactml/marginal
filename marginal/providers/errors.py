"""Errors raised by the model provider abstraction."""


class ProviderError(Exception):
    """Base class for model-provider errors."""


class UnknownProviderError(ProviderError):
    """`ModelSpec.provider` has no registered provider implementation."""


class MissingCredentialsError(ProviderError):
    """The environment variable holding a provider's API key is not set."""


class ProviderResponseError(ProviderError):
    """A provider returned a response that could not be interpreted as requested."""
