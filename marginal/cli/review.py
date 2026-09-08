"""Fetch and summarize a pull request: `marginal review`."""

from __future__ import annotations

import asyncio
import sys

from marginal.config.loader import load_config
from marginal.config.schema import ModelSpec
from marginal.github.client import GitHubClient
from marginal.github.errors import GitHubAPIError, GitHubAuthenticationError, PermissionDeniedError
from marginal.providers.errors import ProviderError
from marginal.providers.factory import get_provider

FINDING_PROMPT_INSTRUCTIONS = (
    "You are reviewing a pull request. Identify the single most important, "
    "actionable issue in the diff below. Be concise and specific: name the "
    "file and explain the problem in 2-3 sentences. If you see nothing worth "
    "flagging, say so plainly."
)


def run_review(repo: str, pr_number: int, path: str = ".", *, comment: bool = False) -> int:
    """Fetch `pr_number` from `repo` and print a plain-text summary.

    Loads `.marginal/config.yaml` under `path` and builds a `GitHubClient`
    gated by its `permissions`, then fetches the pull request's metadata and
    changed files and prints its title, state, base/head SHA, and the
    changed file list.

    If `models.reviewer` is configured, also generates one unvalidated
    finding from that model over the changed files' diffs and appends it to
    the summary. Without it, the summary stays metadata-only, unchanged from
    before this existed.

    If `comment` is set, also posts that same summary as a single PR comment
    via `GitHubClient.create_review(..., event="COMMENT")`. Otherwise posts
    nothing back to GitHub.

    Returns 0 on success. A denied permission, missing/invalid token,
    GitHub API error, or `ProviderError` — whether raised while fetching,
    generating a finding, or (with `comment` set) posting — is caught here,
    printed as a single line to stderr, and turned into exit code 1 instead
    of propagating as a raw traceback.
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

    reviewer_model = config.models.get("reviewer")
    finding = None
    if reviewer_model is not None:
        try:
            finding = asyncio.run(_generate_finding(reviewer_model, files))
        except ProviderError as exc:
            print(f"marginal review: {exc}", file=sys.stderr)
            return 1

    summary_lines = [
        f"PR #{pr_number}: {pull_request['title']}",
        f"State: {pull_request['state']}",
        f"Base: {pull_request['base']['sha']}  Head: {pull_request['head']['sha']}",
        f"Files changed: {len(filenames)}",
        *(f"  {filename}" for filename in filenames),
    ]
    if finding:
        summary_lines += ["", "Finding:", finding]
    summary = "\n".join(summary_lines)

    print(summary)

    if comment:
        try:
            client.create_review(pr_number, summary, event="COMMENT")
        except (PermissionDeniedError, GitHubAuthenticationError, GitHubAPIError) as exc:
            print(f"marginal review: {exc}", file=sys.stderr)
            return 1

    return 0


async def _generate_finding(model_spec: ModelSpec, files: list[dict[str, object]]) -> str:
    """Generate one unvalidated finding from `model_spec` over `files`' diffs."""
    provider = get_provider(model_spec)
    prompt = _build_finding_prompt(files)
    return await provider.generate(prompt)


def _build_finding_prompt(files: list[dict[str, object]]) -> str:
    diff = "\n\n".join(
        f"--- {file['filename']} ---\n{file.get('patch', '')}" for file in files
    )
    return f"{FINDING_PROMPT_INSTRUCTIONS}\n\n{diff}"
