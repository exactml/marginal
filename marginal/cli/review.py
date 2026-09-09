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
from marginal.review import Finding, Severity, filter_findings

SEVERITY_EMOJI = {
    Severity.CRITICAL: "🔴",
    Severity.HIGH: "🟠",
    Severity.MEDIUM: "🟡",
    Severity.LOW: "⚪",
}

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
    changed file list (collapsed behind a Markdown `<details>` block so it
    doesn't dominate the output on larger PRs).

    If `models.reviewer` is configured, also generates one unvalidated,
    structured `Finding` from that model over the changed files' diffs, then
    runs it through `marginal.review.filter_findings`: dropped outright if
    its self-reported `confidence` is below `config.review.confidence_threshold`,
    otherwise capped alongside any others at `config.review.max_comments`
    (highest-confidence first). A finding that survives appends to the
    printed summary as a severity+confidence badge (e.g. `🔴 **Critical** ·
    92% confidence`) followed by its message. Without `models.reviewer`, or
    if the finding gets filtered out, the summary stays metadata-only, same
    as if nothing was generated.

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

    base_lines = _base_lines(pr_number, pull_request, filenames)
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


def _base_lines(pr_number: int, pull_request: dict[str, object], filenames: list[str]) -> list[str]:
    """Render the review header: a title line plus a collapsed file list.

    The file list sits behind a `<details>` block so it doesn't dominate the
    review on larger PRs -- expanding it is one click, not a wall of text.
    """
    file_word = "file" if len(filenames) == 1 else "files"
    lines = [
        "### 🤖 marginal review",
        "",
        f"**PR #{pr_number}: {pull_request['title']}** · {pull_request['state']} · "
        f"`{pull_request['base']['sha']}` → `{pull_request['head']['sha']}` · "
        f"{len(filenames)} {file_word} changed",
    ]
    if filenames:
        lines += [
            "",
            "<details>",
            f"<summary>Changed files ({len(filenames)})</summary>",
            "",
            *(f"- `{filename}`" for filename in filenames),
            "",
            "</details>",
        ]
    return lines


def _finding_badge(finding: Finding, *, with_location: bool) -> str:
    """Render a finding's severity+confidence as one line, e.g.

    `🔴 **Critical** · 92% confidence` -- optionally suffixed with its file
    location, for contexts (like a review's overall body) that aren't
    already anchored to that location the way an inline comment is.
    """
    badge = (
        f"{SEVERITY_EMOJI[finding.severity]} **{finding.severity.value.title()}** · "
        f"{finding.confidence:.0%} confidence"
    )
    if with_location:
        location = finding.file if finding.line is None else f"{finding.file}:{finding.line}"
        badge += f" — `{location}`"
    return badge


def _finding_lines(finding: Finding) -> list[str]:
    """Render one `Finding` as `["", badge, "", message]`, badge and message
    each getting their own paragraph."""
    return ["", _finding_badge(finding, with_location=True), "", finding.message]


def _build_inline_comments(findings: list[Finding]) -> list[dict[str, object]]:
    """Build one GitHub review `comments` entry per line-anchored finding.

    A finding with no `line` is left out here -- callers should fall back to
    including it in the review's overall body instead, so it isn't silently
    dropped. The comment's own file/line already anchors it in the diff, so
    its badge skips repeating the location.
    """
    return [
        {
            "path": finding.file,
            "line": finding.line,
            "body": f"{_finding_badge(finding, with_location=False)}\n\n{finding.message}",
        }
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
