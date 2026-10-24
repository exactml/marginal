"""Environment-variable credential lookup for providers.

Credentials come from the environment only and must never be read from
`.marginal/config.yaml`.
"""

import os

from marginal.providers.errors import MissingCredentialsError


def require_env(var_name: str, *, provider: str) -> str:
    """Return `os.environ[var_name]`, raising `MissingCredentialsError` if unset or empty."""
    value = os.environ.get(var_name)
    if value is None:
        raise MissingCredentialsError(
            f"the {provider!r} provider requires the {var_name} environment variable to be set"
        )
    # marginal-action always exports the variable, so in GitHub Actions a
    # missing secret and a blank one both land here, not above.
    if not value.strip():
        raise MissingCredentialsError(
            f"the {provider!r} provider requires {var_name}, but it is empty -- in GitHub "
            "Actions, check the repository secret exists and has a value (forked PRs "
            "never receive secrets)"
        )
    return value
