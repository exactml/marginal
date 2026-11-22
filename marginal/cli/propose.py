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
    decisions_from_replies,
    extract_claims,
    knowledge_claims,
    render_proposal,
)
from marginal.review.knowledge import posted_knowledge
from marginal.review.render import REVIEW_HEADING
from marginal.review.replies import maintainer_replies

# Permissions that count as a writer; GitHub reports `maintain` as `write`.
_WRITERS = {"admin", "write"}


def run_propose(repo: str, pr_number: int, path: str = ".", *, comment: bool = False) -> int:
    """Print the candidate claims `pr_number` proposes, and with `comment`
    post them as one comment once the PR is merged.

    Only a merged PR proposes anything; an open one prints a preview and a
    closed one says nothing is proposed, and neither is posted. A rerun edits
    the comment instead of posting a second. Which claims become knowledge is
    decided later, outside the PR. No model call. Errors print one stderr
    line and exit 1.
    """
    base_client = GitHubClient(repo, PermissionsConfig())
    try:
        pull_request = base_client.get_pull_request(pr_number)
        config, _ = load_base_config(base_client, pull_request, path)
        client = GitHubClient(repo, config.permissions)
        files = client.get_pull_request_files(pr_number)
        comments = client.list_issue_comments(pr_number)
        # A pyproject line's table can sit above its hunk, so read the whole
        # file on both sides of the diff.
        head, base = {}, {}
        for file in files:
            name = str(file["filename"])
            if PurePosixPath(name).name == "pyproject.toml":
                for side, contents in (("head", head), ("base", base)):
                    text = client.get_file(name, str(pull_request[side]["sha"]))
                    if text is not None:
                        contents[name] = text
        claims = extract_claims(repo.split("/")[-1], files, head, base)
        # A maintainer explaining a marginal finding away is a recorded decision.
        threads = maintainer_replies(client.list_review_comments(pr_number))
        claims += decisions_from_replies(
            (t.path, t.line, reply) for t in threads for reply in t.replies
        )
        # Rules and decisions marginal's reviews found in the same model call.
        reviews = [r.get("body") or "" for r in client.list_reviews(pr_number)]
        knowledge = posted_knowledge(body for body in reviews if REVIEW_HEADING in body)
        claims += knowledge_claims(
            ((k.kind, k.statement, k.about, k.evidence.file, k.evidence.quote) for k in knowledge),
            files,
        )
        state = _state(pull_request)
        body = render_proposal(claims, state)
        print(body)
        if comment and state == "merged":
            _post(client, pr_number, comments, body, claims)
    except (ConfigError, GitHubError) as exc:
        print(f"marginal propose: {exc}", file=sys.stderr)
        return 1
    return 0


def _state(pull_request: dict[str, object]) -> PullRequestState:
    if pull_request.get("merged") or pull_request.get("merged_at"):
        return "merged"
    return "closed" if pull_request.get("state") == "closed" else "open"


def _post(
    client: GitHubClient,
    pr_number: int,
    comments: list[dict[str, object]],
    body: str,
    claims: list[ProposedClaim],
) -> None:
    # Anyone can paste the hidden marker, so only a bot's comment counts, or a
    # writer's: marginal run with a personal token posts as that person.
    existing = next(
        (
            c
            for c in comments
            if PROPOSAL_MARKER in str(c.get("body") or "")
            and (
                (c.get("user") or {}).get("type") == "Bot"
                or client.get_permission(str((c.get("user") or {}).get("login", ""))) in _WRITERS
            )
        ),
        None,
    )
    if existing is None:
        if claims:  # nothing to propose and nothing posted before: stay quiet
            client.create_issue_comment(pr_number, body)
    elif existing.get("body") != body:
        client.update_issue_comment(int(existing["id"]), body)
