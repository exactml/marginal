"""Environment-variable credential lookup for the GitHub client.

Like provider credentials, the token comes from the environment only and
must never be read from `.marginal/config.yaml`.
"""

import os

from marginal.github.errors import GitHubAuthenticationError

GITHUB_TOKEN_ENV_VAR = "GITHUB_TOKEN"


def require_github_token() -> str:
    """Return `os.environ[GITHUB_TOKEN]`, raising `GitHubAuthenticationError` if unset."""
    value = os.environ.get(GITHUB_TOKEN_ENV_VAR)
    if not value:
        raise GitHubAuthenticationError(
            f"the GitHub client requires the {GITHUB_TOKEN_ENV_VAR} environment variable to be set"
        )
    return value
