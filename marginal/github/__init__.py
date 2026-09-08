"""GitHub API integration and auth.

`GitHubClient` wraps the GitHub REST API for one repository, gating every
read/write method on the caller's `PermissionsConfig` before any request is
made.
"""

from marginal.github.client import GitHubClient
from marginal.github.credentials import require_github_token
from marginal.github.errors import (
    GitHubAPIError,
    GitHubAuthenticationError,
    GitHubError,
    GitHubNotFoundError,
    PermissionDeniedError,
)

__all__ = [
    "GitHubAPIError",
    "GitHubAuthenticationError",
    "GitHubClient",
    "GitHubError",
    "GitHubNotFoundError",
    "PermissionDeniedError",
    "require_github_token",
]
