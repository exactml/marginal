"""The rules and decisions a team accepted, from `.marginal/knowledge/` as of
the PR's base commit, so a PR can't change the knowledge it's reviewed by.

One small YAML file per claim, named by its id, so adding or removing one
never conflicts with another:

    .marginal/knowledge/repo/d2e8a1.yaml         repo-wide: every review
    .marginal/knowledge/paths/shop/c41d07.yaml   about shop/: reviews touching it
    .marginal/knowledge/rejected/7be210.yaml     rejected: never loaded or proposed again

The folder is the opt-in: without it a review is unchanged.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ValidationError

from marginal.github.client import GitHubClient

KNOWLEDGE_DIR = ".marginal/knowledge"
REPO_DIR = f"{KNOWLEDGE_DIR}/repo/"
PATHS_DIR = f"{KNOWLEDGE_DIR}/paths/"
REJECTED_DIR = f"{KNOWLEDGE_DIR}/rejected/"
# Each loaded claim costs prompt tokens on every review it reaches.
MAX_ACCEPTED_PER_REVIEW = 15
# Repo-wide claims reach every review, so they get a smaller share.
MAX_REPO_WIDE_PER_REVIEW = 5


class AcceptedClaim(BaseModel):
    # Unknown keys are ignored, so a file written for a newer marginal still loads.
    id: str  # the file's name
    repo: str
    # Repo names or globs (`widgets-*`) it applies to; empty means the
    # repo whose folder holds it, whatever that repo is named.
    applies_to: list[str] = []
    kind: Literal["rule", "decision"]
    statement: str
    # A file, or a folder ending in `/`; a repo-wide claim needs none.
    about: str = ""
    pr: int | None = None
    author: str | None = None


def load_accepted(
    client: GitHubClient, base_sha: str, repo: str, changed: list[str]
) -> list[AcceptedClaim]:
    """The accepted claims at `base_sha` for `repo` (its name; an `owner/`
    prefix is dropped): the newest `MAX_REPO_WIDE_PER_REVIEW` repo-wide ones,
    then the newest about `changed` files, `MAX_ACCEPTED_PER_REVIEW` in all.

    Only files in a changed file's folder or a folder above it are read, all
    in one batch."""
    name = repo.rsplit("/", 1)[-1]
    files = [f for f in client.list_files(KNOWLEDGE_DIR, base_sha) if f.endswith((".yaml", ".yml"))]
    wanted = {PurePosixPath(PATHS_DIR, folder) for path in changed for folder in _folders(path)}
    repo_files = [f for f in files if f.startswith(REPO_DIR)]
    area_files = [f for f in files if f.startswith(PATHS_DIR) and PurePosixPath(f).parent in wanted]
    texts = client.get_files(repo_files + area_files, base_sha) if repo_files or area_files else {}

    def read(path: str) -> AcceptedClaim | None:
        return _applying(parse_accepted(path, texts[path]), name) if path in texts else None

    repo_wide = _newest(read(f) for f in repo_files)
    if len(repo_wide) > MAX_REPO_WIDE_PER_REVIEW:
        _warn(
            f"{len(repo_wide)} repo-wide claims in {REPO_DIR}, but a review loads only the "
            f"newest {MAX_REPO_WIDE_PER_REVIEW}: keep the folder to what applies everywhere"
        )
    repo_wide = repo_wide[:MAX_REPO_WIDE_PER_REVIEW]
    about = [c for c in _newest(read(f) for f in area_files) if _about_changed(c.about, changed)]
    return repo_wide + about[: MAX_ACCEPTED_PER_REVIEW - len(repo_wide)]


def claim_file(claim: AcceptedClaim) -> tuple[str, str]:
    """The path under `paths/` and the YAML text that hold `claim`: the
    folder its `about` sits in, or the folder itself for a folder claim."""
    about = PurePosixPath(claim.about)
    folder = about if claim.about.endswith("/") else about.parent
    path = PurePosixPath(PATHS_DIR, folder, f"{claim.id}.yaml")
    fields = claim.model_dump(exclude={"id"}, exclude_defaults=True)
    return str(path), yaml.safe_dump(fields, sort_keys=False, allow_unicode=True)


def parse_accepted(path: str, text: str) -> AcceptedClaim | None:
    """The claim in file `path`. People edit these files, so a bad one is
    skipped with a warning instead of failing the review."""
    try:
        entry = yaml.safe_load(text)
    except yaml.YAMLError:
        _warn(f"skipping {path}: not valid YAML")
        return None
    if not isinstance(entry, dict):
        _warn(f"skipping {path}: it must hold one claim's fields")
        return None
    try:
        claim = AcceptedClaim.model_validate({**entry, "id": PurePosixPath(path).stem})
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, e["loc"])) or "claim" for e in exc.errors())
        _warn(f"skipping {path}: bad or missing {fields}")
        return None
    about = claim.about.strip().removeprefix("./").lstrip("/")
    if path.startswith(PATHS_DIR):
        if not about:
            _warn(f"skipping {path}: a claim under {PATHS_DIR} needs `about`")
            return None
        # A claim about the folder it sits in is a folder claim, `/` or not.
        if about.rstrip("/") == str(PurePosixPath(path).parent.relative_to(PATHS_DIR)):
            about = about.rstrip("/") + "/"
    return claim.model_copy(update={"about": about})


def _applying(claim: AcceptedClaim | None, repo: str) -> AcceptedClaim | None:
    """`claim` if it applies to `repo`. One without `applies_to` applies here,
    so a local review needn't know the repo's real name."""
    if claim and (not claim.applies_to or any(fnmatch(repo, p) for p in claim.applies_to)):
        return claim
    return None


def _newest(claims: Iterable[AcceptedClaim | None]) -> list[AcceptedClaim]:
    """`claims` without the `None`s, newest PR first; ones without a PR last."""
    return sorted((c for c in claims if c), key=lambda c: -(c.pr or 0))


def _folders(path: str) -> list[str]:
    """The folders `path` sits in, innermost first, down to the root (`.`)."""
    return [str(folder) for folder in PurePosixPath(path).parents]


def _about_changed(about: str, changed: list[str]) -> bool:
    """`about` is a changed file, a folder holding one, or a file in the same
    folder as one, except at the root, where every top-level file is one."""
    if about.endswith("/"):
        return any(path.startswith(about) for path in changed)
    folder = PurePosixPath(about).parent
    if about in changed:
        return True
    return folder != PurePosixPath(".") and any(PurePosixPath(p).parent == folder for p in changed)


def _warn(message: str) -> None:
    print(f"marginal review: warning: {message}", file=sys.stderr)
