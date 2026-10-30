"""The conclusion of the CI run that triggered a review."""

from __future__ import annotations

import json
import os
import sys

from marginal.config.schema import PermissionsConfig
from marginal.github.client import GitHubClient
from marginal.github.errors import GitHubError

# GitHub's documented workflow run conclusions; `None` while a run is in progress.
_CI_CONCLUSIONS = {
    "action_required",
    "cancelled",
    "failure",
    "neutral",
    "skipped",
    "stale",
    "startup_failure",
    "success",
    "timed_out",
}


def read_ci_conclusion(
    client: GitHubClient, permissions: PermissionsConfig, head_sha: str
) -> str | None:
    """The conclusion of the workflow run whose completion triggered this
    review, from the GitHub Actions `workflow_run` event, or `None` if there's
    no such run, it didn't run on `head_sha`, it's still in progress, or it
    can't be read."""
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_run":
        return None
    if not permissions.read.repository:
        return None
    try:
        with open(os.environ["GITHUB_EVENT_PATH"]) as event:
            run_id = json.load(event)["workflow_run"]["id"]
    except (OSError, KeyError, TypeError, ValueError):
        return None
    if not isinstance(run_id, int):
        return None
    try:
        run = client.get_workflow_run(run_id)
    except GitHubError as exc:
        print(
            f"marginal review: warning: couldn't read the CI run's conclusion, skipping: {exc}",
            file=sys.stderr,
        )
        return None
    # A run from an earlier push, or another branch, says nothing about this diff.
    if run.get("head_sha") != head_sha:
        print(
            "marginal review: warning: the CI run that triggered this review didn't run on "
            f"the PR's head commit {head_sha[:7]}, skipping its conclusion",
            file=sys.stderr,
        )
        return None
    conclusion = run.get("conclusion")
    return conclusion if conclusion in _CI_CONCLUSIONS else None
