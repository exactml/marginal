"""The rules and decisions a team accepted, from `.marginal/knowledge.yaml`
as of the PR's base commit, so a PR can't change the knowledge it's reviewed by.

The file is the opt-in: without it a review is unchanged.
"""

from __future__ import annotations

import sys
from fnmatch import fnmatch
from pathlib import PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ValidationError, field_validator

from marginal.github.client import GitHubClient

KNOWLEDGE_PATH = ".marginal/knowledge.yaml"
# The most entries one review loads: each costs prompt tokens on every review.
MAX_ACCEPTED_PER_REVIEW = 15


class AcceptedClaim(BaseModel):
    # Unknown keys are ignored, so a file written for a newer marginal still loads.
    id: str
    repo: str
    # Repo names or globs (`customer-pipeline-*`) it applies to; empty means `repo`.
    applies_to: list[str] = []
    kind: Literal["rule", "decision"]
    statement: str
    # A file, or a folder ending in `/`.
    about: str
    pr: int | None = None
    author: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _id_as_text(cls, value: object) -> object:
        # An unquoted hex id of only digits (`123456`) loads as a YAML number.
        return str(value) if isinstance(value, int) else value


def load_accepted(
    client: GitHubClient, base_sha: str, repo: str, changed: list[str]
) -> list[AcceptedClaim]:
    """The accepted claims at `base_sha` for `repo` about `changed` files."""
    text = client.get_file(KNOWLEDGE_PATH, base_sha)
    if text is None:
        return []
    return matching(parse_accepted(text), repo, changed)


def parse_accepted(text: str) -> list[AcceptedClaim]:
    """Each valid entry of the file's list. People edit the file, so a bad
    entry is skipped with a warning instead of failing the review."""
    try:
        entries = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        _warn(f"{KNOWLEDGE_PATH} isn't valid YAML, so no knowledge is loaded: {exc}")
        return []
    if entries is None:
        return []
    if not isinstance(entries, list):
        _warn(f"{KNOWLEDGE_PATH} must be a list of entries, so no knowledge is loaded")
        return []
    claims = []
    for number, entry in enumerate(entries, 1):
        try:
            claims.append(AcceptedClaim.model_validate(entry))
        except ValidationError as exc:
            fields = ", ".join(".".join(map(str, e["loc"])) or "entry" for e in exc.errors())
            _warn(f"skipping entry {number} in {KNOWLEDGE_PATH}: bad or missing {fields}")
    return claims


def matching(claims: list[AcceptedClaim], repo: str, changed: list[str]) -> list[AcceptedClaim]:
    """The newest `MAX_ACCEPTED_PER_REVIEW` claims for `repo` (its name; an
    `owner/` prefix is dropped) whose `about` is a changed file, a folder
    holding one, or a file in the same folder as one."""
    name = repo.rsplit("/", 1)[-1]
    folders = {PurePosixPath(path).parent for path in changed}

    def about_changed(about: str) -> bool:
        if about.endswith("/"):
            return any(path.startswith(about) for path in changed)
        return about in changed or PurePosixPath(about).parent in folders

    picked = [
        claim
        for claim in reversed(claims)  # the file grows at the end: newest last
        if any(fnmatch(name, pattern) for pattern in claim.applies_to or [claim.repo])
        and about_changed(claim.about)
    ]
    return picked[:MAX_ACCEPTED_PER_REVIEW]


def _warn(message: str) -> None:
    print(f"marginal review: warning: {message}", file=sys.stderr)
