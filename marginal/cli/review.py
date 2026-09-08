"""Fetch and summarize a pull request: `marginal review`."""

from __future__ import annotations

import sys

from marginal.config.loader import load_config
from marginal.github.client import GitHubClient
from marginal.github.errors import GitHubAPIError, GitHubAuthenticationError, PermissionDeniedError


def run_review(repo: str, pr_number: int, path: str = ".") -> int:
    """Fetch `pr_number` from `repo` and print a plain-text summary.

    Loads `.marginal/config.yaml` under `path` and builds a `GitHubClient`
    gated by its `permissions`, then fetches the pull request's metadata and
    changed files and prints its title, state, base/head SHA, and the
    changed file list. Posts nothing back to GitHub — there is no analysis
    yet to report.

    Returns 0 on success. A denied permission, missing/invalid token, or
    GitHub API error is caught here, printed as a single line to stderr, and
    turned into exit code 1 instead of propagating as a raw traceback.
    """
    config = load_config(path)
    client = GitHubClient(repo, config.permissions)

    try:
        pull_request = client.get_pull_request(pr_number)
        files = client.get_pull_request_files(pr_number)
    except (PermissionDeniedError, GitHubAuthenticationError, GitHubAPIError) as exc:
        print(f"marginal review: {exc}", file=sys.stderr)
        return 1

    filenames = [str(file["filename"]) for file in files]

    print(f"PR #{pr_number}: {pull_request['title']}")
    print(f"State: {pull_request['state']}")
    print(f"Base: {pull_request['base']['sha']}  Head: {pull_request['head']['sha']}")
    print(f"Files changed: {len(filenames)}")
    for filename in filenames:
        print(f"  {filename}")

    return 0
