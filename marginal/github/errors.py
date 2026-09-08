"""Errors raised by the GitHub API client."""


class GitHubError(Exception):
    """Base class for GitHub client errors."""


class GitHubAuthenticationError(GitHubError):
    """The `GITHUB_TOKEN` environment variable is missing, or GitHub rejected it."""


class PermissionDeniedError(GitHubError):
    """The operation is blocked by `PermissionsConfig`, not by GitHub itself."""


class GitHubAPIError(GitHubError):
    """GitHub returned a non-2xx response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"GitHub API error {status_code}: {message}")


class GitHubNotFoundError(GitHubAPIError):
    """GitHub returned 404 — the requested resource does not exist."""
