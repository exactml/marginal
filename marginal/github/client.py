"""Synchronous GitHub REST API client, gated by `PermissionsConfig`."""

from __future__ import annotations

from typing import Literal

import requests

from marginal.config.schema import PermissionsConfig
from marginal.github.credentials import require_github_token
from marginal.github.errors import (
    GitHubAPIError,
    GitHubAuthenticationError,
    GitHubNotFoundError,
    PermissionDeniedError,
)

GITHUB_API_URL = "https://api.github.com"

ReviewEvent = Literal["COMMENT", "REQUEST_CHANGES", "APPROVE"]


class GitHubClient:
    """Thin wrapper around the GitHub REST API for one `"owner/name"` repo.

    Every read/write method checks the relevant `PermissionsConfig` flag
    before touching the network, and raises `PermissionDeniedError` (no
    request made) if it's off. Construction itself never reads `GITHUB_TOKEN`
    or makes a network call — both happen only once a permitted method is
    actually called.
    """

    def __init__(
        self,
        repo: str,
        permissions: PermissionsConfig,
        *,
        session: requests.Session | None = None,
        base_url: str = GITHUB_API_URL,
    ) -> None:
        self._repo = repo
        self._permissions = permissions
        self._session = session or requests.Session()
        self._base_url = base_url.rstrip("/")

    # -- reads ---------------------------------------------------------------

    def get_pull_request(self, number: int) -> dict[str, object]:
        """Return the pull request's title, body, base/head SHAs, and state."""
        self._require_read("pull_requests")
        return self._request("GET", f"/repos/{self._repo}/pulls/{number}")

    def get_pull_request_files(self, number: int) -> list[dict[str, object]]:
        """Return the PR's changed files, each with its per-file patch."""
        self._require_read("pull_requests")
        return self._request("GET", f"/repos/{self._repo}/pulls/{number}/files")

    # -- writes ----------------------------------------------------------------

    def create_review(
        self,
        number: int,
        body: str,
        event: ReviewEvent,
        comments: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        """Submit inline `comments`, an overall `body`, and a decision `event`
        as one GitHub "create a review" call.

        Requires `permissions.write.comments`. `event="APPROVE"` additionally
        requires `permissions.write.approve`, independent of `write.comments`.
        """
        self._require_write("comments")
        if event == "APPROVE" and not self._permissions.write.approve:
            raise PermissionDeniedError(
                "create_review(event='APPROVE') requires permissions.write.approve"
            )
        payload = {"body": body, "event": event, "comments": comments or []}
        return self._request("POST", f"/repos/{self._repo}/pulls/{number}/reviews", json=payload)

    # -- internals ---------------------------------------------------------

    def _require_read(self, flag: str) -> None:
        if not getattr(self._permissions.read, flag):
            raise PermissionDeniedError(f"this operation requires permissions.read.{flag}")

    def _require_write(self, flag: str) -> None:
        if not getattr(self._permissions.write, flag):
            raise PermissionDeniedError(f"this operation requires permissions.write.{flag}")

    def _request(self, method: str, path: str, *, json: dict[str, object] | None = None) -> object:
        token = require_github_token()
        response = self._session.request(
            method,
            f"{self._base_url}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            json=json,
        )
        if response.status_code == 401:
            raise GitHubAuthenticationError("GitHub rejected the configured GITHUB_TOKEN")
        if response.status_code == 404:
            raise GitHubNotFoundError(response.status_code, _error_message(response))
        if not response.ok:
            raise GitHubAPIError(response.status_code, _error_message(response))
        return response.json()


def _error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text
    if isinstance(data, dict) and "message" in data:
        return str(data["message"])
    return response.text
