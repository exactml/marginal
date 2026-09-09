"""Fetch and summarize a pull request: `marginal review`."""

from __future__ import annotations

import asyncio
import sys

from marginal.config.loader import load_config
from marginal.config.schema import ModelSpec
from marginal.github.client import GitHubClient
from marginal.github.errors import GitHubAPIError, GitHubAuthenticationError, PermissionDeniedError
from marginal.providers.errors import ProviderError, ProviderResponseError
from marginal.providers.factory import get_provider
from marginal.review import Finding, filter_findings

FINDING_PROMPT_INSTRUCTIONS = (
    "You are reviewing a pull request. Identify the single most important, "
    "actionable issue in the diff below. Report the file it's in, the line "
    "number in the new version of the file if you can identify one (omit it "
    "if you can't), a severity, a confidence between 0.0 and 1.0 for how "
    "likely this is a real, actionable issue (not a false positive or a "
    "stylistic nitpick), and a concise 2-3 sentence explanation of the "
    "problem."
)


def run_review(repo: str, pr_number: int, path: str = ".", *, comment: bool = False) -> int:
    """Fetch `pr_number` from `repo` and print a plain-text summary.

    Loads `.marginal/config.yaml` under `path` and builds a `GitHubClient`
    gated by its `permissions`, then fetches the pull request's metadata and
    changed files and prints its title, state, base/head SHA, and the
    changed file list.

    If `models.reviewer` is configured, also generates one unvalidated,
    structured `Finding` from that model over the changed files' diffs, then
    runs it through `marginal.review.filter_findings`: dropped outright if
    its self-reported `confidence` is below `config.review.confidence_threshold`,
    otherwise capped alongside any others at `config.review.max_comments`
    (highest-confidence first). A finding that survives appends to the
    printed summary (`Finding (severity): file[:line]` followed by the
    message). Without `models.reviewer`, or if the finding gets filtered
    out, the summary stays metadata-only, same as if nothing was generated.

    If `comment` is set, also posts a PR review via
    `GitHubClient.create_review(..., event="COMMENT", comments=...)`. A
    finding anchored to a `line` is posted as an inline `comments` entry
    instead of being folded into the review's overall body -- it still shows
    up in the printed summary above, just not duplicated into the body too.
    One with no identifiable line still falls back to the body, so it isn't
    silently dropped. Omitting `--comment` posts nothing back to GitHub.

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
    finding: Finding | None = None
    if reviewer_model is not None:
        try:
            finding = asyncio.run(_generate_finding(reviewer_model, files))
        except ProviderError as exc:
            print(f"marginal review: {exc}", file=sys.stderr)
            return 1

    findings = [finding] if finding is not None else []
    findings = filter_findings(
        findings,
        confidence_threshold=config.review.confidence_threshold,
        max_comments=config.review.max_comments,
    )
    inline_comments = _build_inline_comments(findings)

    base_lines = [
        f"PR #{pr_number}: {pull_request['title']}",
        f"State: {pull_request['state']}",
        f"Base: {pull_request['base']['sha']}  Head: {pull_request['head']['sha']}",
        f"Files changed: {len(filenames)}",
        *(f"  {filename}" for filename in filenames),
    ]
    summary = "\n".join(base_lines + [line for f in findings for line in _finding_lines(f)])
    print(summary)

    if comment:
        body = "\n".join(
            base_lines + [line for f in findings if f.line is None for line in _finding_lines(f)]
        )
        try:
            client.create_review(pr_number, body, event="COMMENT", comments=inline_comments)
        except (PermissionDeniedError, GitHubAuthenticationError, GitHubAPIError) as exc:
            print(f"marginal review: {exc}", file=sys.stderr)
            return 1

    return 0


def _finding_lines(finding: Finding) -> list[str]:
    """Render one `Finding` as the `["", "Finding (severity): location", message]` block."""
    location = finding.file if finding.line is None else f"{finding.file}:{finding.line}"
    return ["", f"Finding ({finding.severity.value}): {location}", finding.message]


def _build_inline_comments(findings: list[Finding]) -> list[dict[str, object]]:
    """Build one GitHub review `comments` entry per line-anchored finding.

    A finding with no `line` is left out here -- callers should fall back to
    including it in the review's overall body instead, so it isn't silently
    dropped.
    """
    return [
        {"path": finding.file, "line": finding.line, "body": finding.message}
        for finding in findings
        if finding.line is not None
    ]


async def _generate_finding(model_spec: ModelSpec, files: list[dict[str, object]]) -> Finding:
    """Generate one unvalidated `Finding` from `model_spec` over `files`' diffs."""
    provider = get_provider(model_spec)
    prompt = _build_finding_prompt(files)
    result = await provider.generate_structured(prompt, schema=Finding)
    if not isinstance(result, Finding):
        raise ProviderResponseError(
            f"expected a Finding from generate_structured, got {type(result).__name__}"
        )
    return result


def _build_finding_prompt(files: list[dict[str, object]]) -> str:
    diff = "\n\n".join(f"--- {file['filename']} ---\n{file.get('patch', '')}" for file in files)
    return f"{FINDING_PROMPT_INSTRUCTIONS}\n\n{diff}"
