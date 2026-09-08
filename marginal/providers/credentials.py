"""Environment-variable credential lookup for providers.

Per `docs/REQUIREMENTS.md` §4 and §34, provider credentials come from the
environment only and must never be read from `.marginal/config.yaml`.
"""

import os

from marginal.providers.errors import MissingCredentialsError


def require_env(var_name: str, *, provider: str) -> str:
    """Return `os.environ[var_name]`, raising `MissingCredentialsError` if unset."""
    value = os.environ.get(var_name)
    if not value:
        raise MissingCredentialsError(
            f"the {provider!r} provider requires the {var_name} environment variable to be set"
        )
    return value
