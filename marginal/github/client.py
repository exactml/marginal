"""Synchronous GitHub REST API client, gated by `PermissionsConfig`."""

from __future__ import annotations

import base64
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

# Review threads and their resolved state exist only in GitHub's GraphQL API.
_REVIEW_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { id isResolved comments(first: 1) { nodes { databaseId } } }
      }
    }
  }
}
"""

_RESOLVE_THREAD_MUTATION = """
mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) { thread { id } } }
"""


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

    def get_repository(self) -> dict[str, object]:
        """Return the repository's metadata -- a cheap, read-only reachability check."""
        self._require_read("repository")
        return self._request("GET", f"/repos/{self._repo}")

    def get_file(self, path: str, ref: str) -> str | None:
        """Return the text of `path` as of commit `ref`, or `None` if it isn't
        a file there."""
        self._require_read("repository")
        try:
            data = self._request("GET", f"/repos/{self._repo}/contents/{path}", params={"ref": ref})
        except GitHubNotFoundError:
            return None
        if not isinstance(data, dict) or "content" not in data:
            return None
        return base64.b64decode(str(data["content"])).decode()

    def get_pull_request(self, number: int) -> dict[str, object]:
        """Return the pull request's title, body, base/head SHAs, and state."""
        self._require_read("pull_requests")
        return self._request("GET", f"/repos/{self._repo}/pulls/{number}")

    def get_pull_request_files(self, number: int) -> list[dict[str, object]]:
        """Return the PR's changed files, each with its per-file patch.

        Follows every page GitHub returns (up to its own 3000-file-per-PR
        cap) instead of stopping at the first page, so a PR with more files
        than fit on one page isn't silently truncated.
        """
        self._require_read("pull_requests")
        return self._get_all_pages(f"/repos/{self._repo}/pulls/{number}/files")

    def get_compare_files(self, base: str, head: str) -> list[dict[str, object]]:
        """Return the files changed between commits `base` and `head`, in the
        same shape as `get_pull_request_files`.

        One request: GitHub's compare API returns at most 300 files and
        doesn't page them.
        """
        self._require_read("repository")
        data = self._request("GET", f"/repos/{self._repo}/compare/{base}...{head}")
        return data.get("files", [])

    def list_review_comments(self, number: int) -> list[dict[str, object]]:
        """Return every inline review comment on the PR, across all pages."""
        self._require_read("pull_requests")
        return self._get_all_pages(f"/repos/{self._repo}/pulls/{number}/comments")

    def list_reviews(self, number: int) -> list[dict[str, object]]:
        """Return every review submitted on the PR, across all pages."""
        self._require_read("pull_requests")
        return self._get_all_pages(f"/repos/{self._repo}/pulls/{number}/reviews")

    def list_issue_comments(self, number: int) -> list[dict[str, object]]:
        """Return every top-level (non-review) comment on the PR, across all pages."""
        self._require_read("pull_requests")
        return self._get_all_pages(f"/repos/{self._repo}/issues/{number}/comments")

    def list_review_threads(self, number: int) -> list[dict[str, object]]:
        """Return every review thread on the PR as `{"id", "is_resolved",
        "comment_id"}`, where `comment_id` is the REST id of the thread's first
        comment -- the id `list_review_comments` reports for it."""
        self._require_read("pull_requests")
        owner, name = self._repo.split("/", 1)
        threads: list[dict[str, object]] = []
        cursor = None
        while True:
            data = self._graphql(
                _REVIEW_THREADS_QUERY,
                {"owner": owner, "name": name, "number": number, "cursor": cursor},
            )
            page = data["repository"]["pullRequest"]["reviewThreads"]
            threads += [
                {
                    "id": node["id"],
                    "is_resolved": node["isResolved"],
                    "comment_id": next((c["databaseId"] for c in node["comments"]["nodes"]), None),
                }
                for node in page["nodes"]
            ]
            if not page["pageInfo"]["hasNextPage"]:
                return threads
            cursor = page["pageInfo"]["endCursor"]

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

    def reply_to_review_comment(self, number: int, comment_id: int, body: str) -> dict[str, object]:
        """Post `body` as a reply in the thread of review comment `comment_id`.

        Requires `permissions.write.comments`, like `create_review`.
        """
        self._require_write("comments")
        return self._request(
            "POST",
            f"/repos/{self._repo}/pulls/{number}/comments/{comment_id}/replies",
            json={"body": body},
        )

    def resolve_review_thread(self, thread_id: str) -> None:
        """Mark review thread `thread_id` resolved, as the "Resolve conversation"
        button does. Requires `permissions.write.comments`."""
        self._require_write("comments")
        self._graphql(_RESOLVE_THREAD_MUTATION, {"id": thread_id})

    # -- internals ---------------------------------------------------------

    def _require_read(self, flag: str) -> None:
        if not getattr(self._permissions.read, flag):
            raise PermissionDeniedError(f"this operation requires permissions.read.{flag}")

    def _require_write(self, flag: str) -> None:
        if not getattr(self._permissions.write, flag):
            raise PermissionDeniedError(f"this operation requires permissions.write.{flag}")

    def _get_all_pages(self, path: str) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        page = 1
        while True:
            batch = self._request("GET", path, params={"per_page": 100, "page": page})
            items.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return items

    def _graphql(self, query: str, variables: dict[str, object]) -> dict[str, object]:
        # GraphQL reports failures as HTTP 200 with an `errors` list.
        result = self._request("POST", "/graphql", json={"query": query, "variables": variables})
        if result.get("errors"):
            messages = "; ".join(str(e.get("message", e)) for e in result["errors"])
            raise GitHubAPIError(200, messages)
        return result["data"]

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
    ) -> object:
        token = require_github_token()
        response = self._session.request(
            method,
            f"{self._base_url}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            json=json,
            params=params,
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
