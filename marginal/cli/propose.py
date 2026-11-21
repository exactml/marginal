"""`marginal propose`: post the knowledge a pull request proposes (ADR 0011)."""

from __future__ import annotations

import sys
from pathlib import PurePosixPath

from marginal.config.errors import ConfigError
from marginal.config.schema import PermissionsConfig
from marginal.context import load_base_config
from marginal.github.client import GitHubClient
from marginal.github.errors import GitHubError
from marginal.oic.services.proposals import (
    PROPOSAL_MARKER,
    ProposedClaim,
    PullRequestState,
    extract_claims,
    render_proposal,
    requested_drops,
)

# Permissions that may drop a claim; GitHub reports `maintain` as `write`.
_CAN_DROP = {"admin", "write"}


def run_propose(repo: str, pr_number: int, path: str = ".", *, comment: bool = False) -> int:
    """Print the claims `pr_number`'s diff proposes, and with `comment` post
    them as one PR comment that later runs edit in place.

    The PR's state picks the wording: open (would record), merged (accepted)
    or closed without merging (not recorded). A `/marginal drop <id>` counts
    only from an account with write access to the repository. No model call.
    Errors print one stderr line and exit 1.
    """
    base_client = GitHubClient(repo, PermissionsConfig())
    try:
        pull_request = base_client.get_pull_request(pr_number)
        config, _ = load_base_config(base_client, pull_request, path)
        client = GitHubClient(repo, config.permissions)
        files = client.get_pull_request_files(pr_number)
        comments = client.list_issue_comments(pr_number)
        # A pyproject line's table can sit above its hunk, so read the whole file.
        contents = {}
        for file in files:
            name = str(file["filename"])
            if PurePosixPath(name).name == "pyproject.toml":
                text = client.get_file(name, str(pull_request["head"]["sha"]))
                if text is not None:
                    contents[name] = text
        claims = extract_claims(repo.split("/")[-1], files, contents)
        body = render_proposal(claims, _allowed_drops(client, comments), _state(pull_request))
        print(body)
        if comment:
            _post(client, pr_number, comments, body, claims)
    except (ConfigError, GitHubError) as exc:
        print(f"marginal propose: {exc}", file=sys.stderr)
        return 1
    return 0


def _state(pull_request: dict[str, object]) -> PullRequestState:
    if pull_request.get("merged") or pull_request.get("merged_at"):
        return "merged"
    return "closed" if pull_request.get("state") == "closed" else "open"


def _allowed_drops(client: GitHubClient, comments: list[dict[str, object]]) -> dict[str, str]:
    """Claim id → who dropped it, counting only accounts that can write to the repo."""
    permissions: dict[str, str] = {}
    dropped: dict[str, str] = {}
    for login, ids in requested_drops(comments):
        if login not in permissions:
            permissions[login] = client.get_permission(login)
        if permissions[login] in _CAN_DROP:
            for claim_id in ids:
                dropped.setdefault(claim_id, login)
    return dropped


def _post(
    client: GitHubClient,
    pr_number: int,
    comments: list[dict[str, object]],
    body: str,
    claims: list[ProposedClaim],
) -> None:
    # Only a bot's comment: anyone can paste the hidden marker into their own.
    existing = next(
        (
            c
            for c in comments
            if PROPOSAL_MARKER in str(c.get("body") or "")
            and (c.get("user") or {}).get("type") == "Bot"
        ),
        None,
    )
    if existing is None:
        if claims:  # nothing to propose and nothing posted before: stay quiet
            client.create_issue_comment(pr_number, body)
    elif existing.get("body") != body:
        client.update_issue_comment(int(existing["id"]), body)
