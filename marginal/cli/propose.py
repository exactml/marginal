"""`marginal propose`: post the knowledge a pull request proposes (ADR 0011)."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import PurePosixPath

from marginal.config.errors import ConfigError
from marginal.config.schema import PermissionsConfig
from marginal.context import load_base_config
from marginal.context.knowledge import KNOWLEDGE_DIR, REJECTED_DIR, AcceptedClaim, claim_file
from marginal.github.client import GitHubClient
from marginal.github.errors import GitHubError
from marginal.oic.domain.schema import Relation
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
# The account a workflow's GITHUB_TOKEN posts as, which is how marginal posts in CI.
_WORKFLOW_BOT = "github-actions[bot]"
# The branch of the one open knowledge PR, which each merged PR adds files to.
KNOWLEDGE_BRANCH = "marginal/knowledge"
_KNOWLEDGE_PR_TITLE = "marginal: knowledge to review"
# Each file marginal commits to the knowledge branch is named in its commit message,
# so a later run can tell which of them the team deleted.
_COMMITTED_FILE = re.compile(
    r"(?:Propose knowledge from|Record knowledge rejected in) #\d+: (?P<path>.+\.yaml)$"
)
_KNOWLEDGE_PR_BODY = """Rules and decisions marginal found in merged pull requests, one file each \
under `.marginal/knowledge/paths/`. Once merged, a review loads the ones about the files \
it changes.

- **Accept** a claim: keep its file.
- **Reject** it: delete the file. Once this PR is merged or closed, marginal records it \
under `.marginal/knowledge/rejected/` and doesn't propose it again; delete that record to \
let it come back.
- **Fix** it: edit the file.
- **Make it repo-wide**, so every review loads it: move the file to `.marginal/knowledge/repo/`.

Merging accepts what's left. Each merged PR adds to this one until it's merged; \
closing it rejects everything in it."""


def run_propose(repo: str, pr_number: int, path: str = ".", *, comment: bool = False) -> int:
    """Print the candidate claims `pr_number` proposes, and with `comment`
    post them as one comment once the PR is merged.

    Only a merged PR proposes anything; an open one prints a preview and a
    closed one says nothing is proposed, and neither is posted. A rerun edits
    the comment instead of posting a second. Which claims become knowledge is
    decided later, outside the PR. No model call. Errors print one stderr
    line and exit 1.

    With `proposals.enabled` off (the default) it does nothing and prints nothing.
    """
    base_client = GitHubClient(repo, PermissionsConfig())
    try:
        pull_request = base_client.get_pull_request(pr_number)
        config, _ = load_base_config(base_client, pull_request, path)
        if not config.proposals.enabled:
            return 0
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
        trusted = _trusted_author(client)
        # A maintainer explaining a marginal finding away is a recorded decision;
        # a reply from someone without write access isn't a maintainer's.
        threads = maintainer_replies(
            c for c in client.list_review_comments(pr_number) if trusted(c)
        )
        # The person who replied made the decision, not necessarily the PR's author.
        claims += decisions_from_replies(
            (t.path, t.line, reply, author)
            for t in threads
            for reply, author in zip(t.replies, t.authors, strict=True)
        )
        # Rules and decisions marginal's reviews found in the same model call.
        reviews = [
            r.get("body") or ""
            for r in client.list_reviews(pr_number)
            if REVIEW_HEADING in (r.get("body") or "") and trusted(r)
        ]
        # Only the newest: each review sees the whole PR, and the model words the
        # same rule differently each time, so older ones would add near-duplicates.
        with_knowledge = [body for body in reviews if posted_knowledge([body])]
        knowledge = posted_knowledge(with_knowledge[-1:])
        claims += knowledge_claims(
            (
                (
                    k.kind,
                    k.statement,
                    k.about,
                    k.evidence.file,
                    k.evidence.line,
                    k.evidence.quote,
                    k.replaces,
                )
                for k in knowledge
            ),
            files,
        )
        state = _state(pull_request)
        body = render_proposal(claims, state)
        print(body)
        if comment and state == "merged":
            # Pushing is off by default: marginal otherwise never pushes.
            if config.permissions.write.push:
                try:
                    knowledge_pr = _add_to_knowledge_pr(
                        client, repo, pr_number, pull_request, claims
                    )
                except GitHubError as exc:  # the comment is the main output: still post it
                    print(
                        f"marginal propose: warning: couldn't add to the knowledge PR: {exc}",
                        file=sys.stderr,
                    )
                    knowledge_pr = None
                if knowledge_pr:
                    body += f"\n\nAdded to {knowledge_pr} for the team to review."
            _post(client, pr_number, comments, body, claims, trusted)
    except (ConfigError, GitHubError) as exc:
        print(f"marginal propose: {exc}", file=sys.stderr)
        return 1
    return 0


def _add_to_knowledge_pr(
    client: GitHubClient,
    repo: str,
    pr_number: int,
    pull_request: dict[str, object],
    claims: list[ProposedClaim],
) -> str | None:
    """Add one file per rule or decision in `claims` to the knowledge branch,
    and open the knowledge PR if none is open. Returns its URL, or `None`
    with no rule or decision to add, or for a PR merged into a branch other
    than the default one: reviews read knowledge from the default branch."""
    base = str(pull_request["base"]["ref"])
    if base != (pull_request["base"].get("repo") or {}).get("default_branch"):
        return None
    kinds = {Relation.CONSTRAINS: "rule", Relation.DECISION_ABOUT: "decision"}
    pr_author = str((pull_request.get("user") or {}).get("login") or "")
    files = [
        claim_file(
            AcceptedClaim(
                id=claim.id,
                repo=repo.split("/")[-1],
                kind=kinds[claim.relation],
                statement=claim.subject.split(": ", 1)[-1],
                about=claim.object,
                pr=pr_number,
                # The replier for a decision from a reply; else the PR's author.
                author=claim.author or pr_author or None,
            )
        )
        for claim in claims
        if claim.relation in kinds
    ]
    if not files:
        return None
    pulls = client.list_pull_requests(KNOWLEDGE_BRANCH)
    knowledge_pr = next((p for p in pulls if p["state"] == "open"), None)
    branch_sha = client.get_branch_sha(KNOWLEDGE_BRANCH)
    # A merged or closed PR's files are done with (a closed one was rejected), so
    # start over from the base branch. Files no PR carried yet, because opening
    # one failed, stay: the PR is opened below.
    restart = knowledge_pr is None and (
        branch_sha is None or any(p["head"]["sha"] == branch_sha for p in pulls)
    )
    if restart:
        base_sha = client.get_branch_sha(base)
        if base_sha is None:
            raise GitHubError(f"base branch {base} not found")
        # The newest PR that isn't open is the one just merged or closed.
        previous = next((p for p in pulls if p["state"] != "open"), None)
        rejected = _rejected(client, previous, base_sha) if previous else {}
        client.set_branch(KNOWLEDGE_BRANCH, base_sha)
        for path, text in rejected.items():
            client.create_file(
                path,
                text,
                KNOWLEDGE_BRANCH,
                f"Record knowledge rejected in #{previous['number']}: {path}",
            )
    # By id anywhere in the folder: the team may have moved a claim to `repo/`, and
    # one under `rejected/` isn't proposed again.
    known = {PurePosixPath(f).stem for f in client.list_files(KNOWLEDGE_DIR, KNOWLEDGE_BRANCH)}
    new = [(path, text) for path, text in files if PurePosixPath(path).stem not in known]
    for path, text in new:
        client.create_file(
            path, text, KNOWLEDGE_BRANCH, f"Propose knowledge from #{pr_number}: {path}"
        )
    if knowledge_pr is None and restart and not new:
        return None  # all accepted already: a PR with no commits can't be opened
    if knowledge_pr is None:
        knowledge_pr = client.create_pull_request(
            KNOWLEDGE_BRANCH, base, _KNOWLEDGE_PR_TITLE, _KNOWLEDGE_PR_BODY
        )
    return str(knowledge_pr["html_url"])


def _rejected(client: GitHubClient, previous: dict[str, object], base_sha: str) -> dict[str, str]:
    """The files to record under `rejected/`, by path: each claim marginal
    committed to the knowledge PR `previous` whose id is nowhere in the
    knowledge folder at `base_sha`, because the team deleted it or closed the
    PR. Each holds the claim as marginal proposed it.

    Records a closed PR carried are kept too; for a merged one the base is the
    record, since the team may have deleted one to let its claim come back."""
    on_base = {PurePosixPath(f).stem for f in client.list_files(KNOWLEDGE_DIR, base_sha)}
    merged = bool(previous.get("merged_at"))
    committed: dict[str, tuple[str, str]] = {}
    for commit in client.list_pull_request_commits(int(previous["number"])):
        match = _COMMITTED_FILE.match(str(commit["commit"]["message"]).splitlines()[0])
        if not match or (merged and match["path"].startswith(REJECTED_DIR)):
            continue
        claim_id = PurePosixPath(match["path"]).stem
        if claim_id not in on_base:
            committed[f"{REJECTED_DIR}{claim_id}.yaml"] = (match["path"], str(commit["sha"]))
    texts = {path: client.get_file(source, sha) for path, (source, sha) in committed.items()}
    return {path: text for path, text in texts.items() if text is not None}


def _trusted_author(client: GitHubClient) -> Callable[[dict[str, object]], bool]:
    """Whether a comment or review's author speaks for the repository: the
    account marginal posts as with the workflow's token, or someone with write
    access (marginal run with a personal token posts as that person). Any other
    bot is not trusted: it may echo text someone else wrote. Each login's
    permission is looked up once."""
    permissions: dict[str, str] = {}

    def trusted(item: dict[str, object]) -> bool:
        user = item.get("user") or {}
        login = str(user.get("login", ""))
        # shortcut: only the GITHUB_TOKEN bot; a GitHub App token posts as its own
        # bot login, which would need a setting under `proposals:`.
        if login == _WORKFLOW_BOT:
            return True
        if not login or user.get("type") == "Bot":  # other bots aren't collaborators
            return False
        if login not in permissions:
            permissions[login] = client.get_permission(login)
        return permissions[login] in _WRITERS

    return trusted


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
    trusted: Callable[[dict[str, object]], bool],
) -> None:
    # Anyone can paste the hidden marker, so only a trusted author's comment counts.
    existing = next(
        (c for c in comments if PROPOSAL_MARKER in str(c.get("body") or "") and trusted(c)),
        None,
    )
    if existing is None:
        if claims:  # nothing to propose and nothing posted before: stay quiet
            client.create_issue_comment(pr_number, body)
    elif existing.get("body") != body:
        client.update_issue_comment(int(existing["id"]), body)
