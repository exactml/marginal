"""Fetch and summarize a pull request: `marginal review`."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import math
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from marginal.config.errors import ConfigError
from marginal.config.loader import CONFIG_RELATIVE_PATH, load_config, parse_config
from marginal.config.schema import MarginalConfig, ModelSpec, PermissionsConfig, ReviewConfig
from marginal.github.client import GitHubClient
from marginal.github.errors import (
    GitHubAPIError,
    GitHubAuthenticationError,
    GitHubError,
    PermissionDeniedError,
)
from marginal.graph import ChangedDefinition, build_symbol_graph, find_out_of_diff_callers
from marginal.graph.diff import _hunk_ranges
from marginal.policy import load_policies
from marginal.providers.errors import MissingCredentialsError, ProviderError, ProviderResponseError
from marginal.providers.factory import get_provider
from marginal.review import Finding, Severity, filter_findings
from marginal.review.dedup import (
    finding_fingerprint,
    fingerprint_marker,
    nearby_fingerprints,
    posted_fingerprints,
)
from marginal.review.redact import redact_secrets
from marginal.review.replies import ReplyThread, maintainer_replies

SEVERITY_EMOJI = {
    Severity.CRITICAL: "🔴",
    Severity.HIGH: "🟠",
    Severity.MEDIUM: "🟡",
    Severity.LOW: "⚪",
}

# A model can return at most this many findings from one review -- well above
# `config.review.max_comments`'s default, so that setting has real findings
# left to cap rather than just passing everything through.
MAX_FINDINGS_PER_REVIEW = 20

# Total out-of-diff caller snippets folded into the prompt across every
# changed definition -- bounds the prompt against a definition with a huge
# fan-out, independent of repo size.
MAX_GRAPH_CONTEXT_CALLERS = 10

# Lines of source shown above and below a caller's own line.
_GRAPH_CONTEXT_SNIPPET_RADIUS = 2

# Most-recent maintainer-answered threads folded into the prompt, and the
# characters kept from each thread's comment and from its replies -- bounds
# the prompt on a PR with a long back-and-forth.
MAX_REPLY_THREADS = 10
_REPLY_COMMENT_CHARS = 600
_REPLY_TEXT_CHARS = 1500

# Rough characters-per-token ratio for estimating a prompt's size without a
# provider-specific tokenizer. Code and diffs tokenize denser than English
# prose (~4 chars/token), so 3 errs toward over-counting: the cap stays a
# real ceiling rather than one a prompt can quietly overshoot.
_CHARS_PER_TOKEN = 3

OutputFormat = Literal["text", "json"]

# Every review marginal posts opens with this, which is how a re-run spots
# that it has already reviewed a PR.
REVIEW_HEADING = "### 🤖 marginal review"

# Shown when no model reviewed the diff; without it, a fresh `marginal init`
# setup posts just a title and file list with nothing pointing at the gap.
NO_REVIEWER_NOTICE = (
    "ℹ️ **No reviewer model configured**, so only the PR's metadata is shown. Set "
    "`models.reviewer` in `.marginal/config.yaml` to have a model review the diff."
)

FINDING_PROMPT_INSTRUCTIONS = (
    "You are reviewing a pull request. Identify the most important, "
    "actionable issues in the diff below -- as many as are genuinely "
    f"warranted, up to {MAX_FINDINGS_PER_REVIEW}. Return an empty list if "
    "nothing in the diff is worth flagging. For each issue, report the file "
    "it's in, the line number in the new version of the file if you can "
    "identify one (omit it if you can't), a severity, a confidence between "
    "0.0 and 1.0 for how likely this is a real, actionable issue (not a "
    "false positive or a stylistic nitpick), and a concise 2-3 sentence "
    "explanation of the problem."
)


class _PromptOverBudget(Exception):
    """The built prompt's estimated size exceeds `review.max_prompt_tokens`."""


class _FindingsResponse(BaseModel):
    """Structured-output wrapper: the bounded list of findings for one review."""

    model_config = ConfigDict(extra="forbid")

    findings: list[Finding] = Field(max_length=MAX_FINDINGS_PER_REVIEW)


def run_review(
    repo: str,
    pr_number: int | None,
    path: str = ".",
    *,
    base: str | None = None,
    head: str | None = None,
    comment: bool = False,
    output_format: OutputFormat = "text",
) -> int:
    """Fetch `pr_number` from `repo` and print a summary in `output_format`.

    With `pr_number=None`, reviews the diff between commits `base` and `head`
    instead (`GitHubClient.get_compare_files`), with config and policies as of
    `base`. Nothing PR-only happens then: no earlier comments are read, so no
    maintainer replies or dedup, and `comment` must be off.

    Fetches the pull request, then loads `.marginal/config.yaml` and its
    policy files as of the PR's base commit (`_load_base_config`), so the PR
    can't change the rules it's reviewed by; only when the base has no config
    yet does it fall back to the one under `path`. It builds a `GitHubClient`
    gated by that config's `permissions` and fetches the changed files.
    With the default `output_format="text"`, prints its
    title, state, base/head SHA, and the changed file list (collapsed behind
    a Markdown `<details>` block so it doesn't dominate the output on larger
    PRs).

    With `output_format="json"`, prints the object built by
    `_build_json_result` instead. `--format` only changes what reaches
    stdout: it never changes what (if anything) gets posted to GitHub, and
    JSON mode prints nothing until the run has fully succeeded, so stdout is
    always either one complete JSON object or nothing at all -- never a
    partial one. Errors keep printing as a single plain-text line to stderr
    in both formats, so a JSON consumer distinguishes success from failure
    by exit code rather than by parsing stderr. Any other `output_format`
    raises `ValueError` before any network call is made.

    If `models.reviewer` is configured, also generates a bounded list of
    unvalidated, structured `Finding`s (up to `MAX_FINDINGS_PER_REVIEW`) from
    that model over the changed files' diffs -- each file's patch run
    through `marginal.review.redact_secrets` first, so a diff containing a
    recognizable secret shape never reaches the model with that value intact
    -- plus the content of any `config.policies` files (loaded via
    `marginal.policy.load_policies`, relative to `path`; a missing file is
    skipped with a warning rather than failing the review) and, under a
    separate "never flag" instruction, any `config.anti_policies` files
    (loaded the same way) describing deliberate tradeoffs the repo doesn't
    want re-litigated, then runs the
    list through `marginal.review.filter_findings`: each finding is dropped
    outright if its self-reported `confidence` is below
    `config.review.confidence_threshold`, and the survivors are capped at
    `config.review.max_comments` (highest-confidence first). Each finding
    that survives appends to the printed summary as a severity+confidence
    badge (e.g. `🔴 **Critical** · 92% confidence`) followed by its message.
    Without `models.reviewer`, or if every finding gets filtered out, the
    summary stays metadata-only, same as if nothing was generated.

    With `config.review.self_reflect`, the findings first go back to the same
    model with the diff (`marginal.cli.critique.critique_findings`), which
    can lower each one's confidence or drop it (never raise it), so the
    threshold and cap act on that second look. It's one extra call, skipped
    when nothing was found, and best-effort: over budget or failed, the
    findings pass on unchanged.

    Before any model call, the fully built prompt's size is estimated
    (`_estimate_tokens`, a length heuristic) and checked against
    `config.review.max_prompt_tokens`. Over the cap, the model is never
    called -- marginal bills the user's own API key, so an unexpectedly huge
    prompt is skipped rather than paid for. That's a degraded review, not a
    failure: it prints a one-line stderr notice, exits 0, and the summary
    stays metadata-only plus a `⚠️ **Review skipped**` line, so it can't be
    mistaken for a review that found nothing. With `comment` set that
    summary is posted even if marginal already reviewed this PR, since the
    new push went unreviewed; `--format json` reports
    `"prompt_over_budget": true`.

    With `config.context.code_graph` (on by default), the prompt also names
    any definition this diff changes that's called from a file outside the
    diff -- `marginal.graph.build_symbol_graph` indexes the repo, and
    `marginal.graph.find_out_of_diff_callers` maps the diff's changed
    definitions to those out-of-diff call sites, each folded in as a short
    source snippet (bounded to `MAX_GRAPH_CONTEXT_CALLERS` total). This is
    best-effort: a definition with no out-of-diff callers, `code_graph`
    turned off, or the graph failing to build at all (not a git checkout,
    `git` missing, a tracked file with invalid syntax) all leave the prompt
    exactly as it would be without this section -- never something that
    fails the review itself.

    The prompt also carries any maintainer replies to marginal's own inline
    comments on this PR (`marginal.review.replies.maintainer_replies`), so
    the model doesn't raise a point a maintainer already answered again
    unless the code it's about changed. Bounded to the `MAX_REPLY_THREADS`
    most recent threads, each clipped; with no such replies the prompt is
    unchanged. Reading the comments needs only `permissions.read`, so this
    happens with or without `comment`.

    Changed files matching `config.review.ignore_paths` (lockfiles and
    minified assets by default; see `_is_ignored`) stay in the file list but
    never reach the model or the code graph, and the summary says how many
    were left out. If every changed file is ignored, the model isn't called
    at all and the summary carries no verdict, since nothing was reviewed.

    If redaction actually masked something, the summary also gets a
    `⚠️ **Redacted a likely secret**` line naming the affected file(s) --
    this is folded into the same body/summary rather than becoming a
    second comment, so the client learns about it without a new
    `create_review` call.

    Similarly, if the reviewed file list doesn't fully cover what changed --
    GitHub's own 3000-file-per-PR cap left files out, or a file's patch was
    omitted for being too large or binary -- the summary gets a
    `⚠️ **Incomplete review coverage**` and/or `⚠️ **No diff available**`
    line naming the gap, so a review with no findings can't be mistaken for
    one that looked at everything and found nothing.

    If `comment` is set, also posts a PR review via
    `GitHubClient.create_review(..., event="COMMENT", comments=...)`. Each
    finding anchored to a `line` is posted as an inline `comments` entry
    instead of being folded into the review's overall body -- it still shows
    up in the printed summary above, just not duplicated into the body too.
    One with no identifiable line still falls back to the body, so it isn't
    silently dropped. Omitting `--comment` posts nothing back to GitHub.

    With `comment` set, a PR `_skip_reason` names -- `review.enabled` off,
    a draft, a bot author, or a `review.skip_labels` label -- gets no model
    call and nothing posted: one stderr line says why and it exits 0.

    Returns 0 on success. An invalid `.marginal/config.yaml` (`ConfigError`),
    a denied permission, missing/invalid token, GitHub API error, or
    `ProviderError` — whether raised while loading config, fetching,
    generating a finding, or (with `comment` set) posting — is caught here,
    printed as a single line to stderr, and turned into exit code 1 instead
    of propagating as a raw traceback. The one exception is a configured
    reviewer missing its required credentials (`MissingCredentialsError`),
    which exits 3 instead of 1 -- distinct enough for a caller (like
    `marginal-action`) to tell "needs fixing" apart from "expected, e.g. a
    forked PR that never got the secret" and react differently.
    """
    if output_format not in get_args(OutputFormat):
        raise ValueError(f"unknown output format: {output_format!r}")

    # Config and policies come from the PR's base commit, not its checkout:
    # otherwise the PR could rewrite the rules it's reviewed by. Read with
    # default permissions, since the config's own `permissions` aren't known yet.
    base_client = GitHubClient(repo, PermissionsConfig())
    try:
        pull_request = (
            base_client.get_pull_request(pr_number)
            if pr_number is not None
            # Just enough of a PR's shape for the shared code below.
            else {"base": {"sha": base, "repo": {"full_name": repo}}, "head": {"sha": head}}
        )
        config, base_sha = _load_base_config(base_client, pull_request, path)
        reviewer_model = config.models.get("reviewer")
        policies: list[tuple[str, str]] = []
        anti_policies: list[tuple[str, str]] = []
        if reviewer_model is not None:
            policies = _load_base_policies(base_client, base_sha, path, config.policies)
            anti_policies = _load_base_policies(base_client, base_sha, path, config.anti_policies)
    except ConfigError as exc:
        print(f"marginal review: {exc}", file=sys.stderr)
        return 1
    except (PermissionDeniedError, GitHubAuthenticationError, GitHubAPIError) as exc:
        print(f"marginal review: {exc}", file=sys.stderr)
        return 1
    client = GitHubClient(repo, config.permissions)

    try:
        files = (
            client.get_pull_request_files(pr_number)
            if pr_number is not None
            else client.get_compare_files(base, head)
        )
        # Read once, up front: the prompt needs maintainer replies before
        # generating, and `--comment` needs the posted markers for dedup.
        review_comments = (
            client.list_review_comments(pr_number)
            if pr_number is not None and (reviewer_model is not None or comment)
            else []
        )
    except (PermissionDeniedError, GitHubAuthenticationError, GitHubAPIError) as exc:
        print(f"marginal review: {exc}", file=sys.stderr)
        return 1

    # Only with `--comment`, so a draft can still be previewed locally.
    skip_reason = _skip_reason(config.review, pull_request) if comment else None
    if skip_reason is not None:
        print(f"marginal review: skipped, nothing posted -- {skip_reason}", file=sys.stderr)
        return 0

    filenames = [str(file["filename"]) for file in files]

    findings: list[Finding] = []
    redacted_files: list[str] = []
    coverage_lines: list[str] = []
    over_budget: _PromptOverBudget | None = None
    ignore_paths = config.review.ignore_paths
    reviewed_files = [f for f in files if not _is_ignored(str(f["filename"]), ignore_paths)]
    if reviewer_model is not None:
        coverage_lines = _ignored_lines(len(files) - len(reviewed_files))
        coverage_lines += _coverage_warning_lines(pull_request, files, ignore_paths)
    # Every changed file is ignored: there's no diff to send, so no model call.
    if reviewer_model is not None and reviewed_files:
        redacted = _redact_patches(reviewed_files)
        redacted_files = _redacted_filenames(reviewed_files, redacted)
        graph_context = _build_graph_context(
            path, reviewed_files, enabled=config.context.code_graph
        )
        replies = maintainer_replies(review_comments)
        try:
            findings = asyncio.run(
                _generate_findings(
                    reviewer_model,
                    redacted,
                    policies,
                    graph_context,
                    path,
                    replies,
                    max_prompt_tokens=config.review.max_prompt_tokens,
                    anti_policies=anti_policies,
                )
            )
        except _PromptOverBudget as exc:
            over_budget = exc
            print(
                f"marginal review: skipped generating findings: {exc} -- raise the cap in "
                ".marginal/config.yaml or split the PR to review it",
                file=sys.stderr,
            )
        except MissingCredentialsError as exc:
            print(f"marginal review: {exc}", file=sys.stderr)
            return 3
        except ProviderError as exc:
            print(f"marginal review: {exc}", file=sys.stderr)
            return 1
        if config.review.self_reflect and findings:
            # Imported here: `marginal.cli.critique` imports helpers from this module.
            from marginal.cli.critique import critique_findings

            findings = critique_findings(
                reviewer_model,
                findings,
                redacted,
                max_prompt_tokens=config.review.max_prompt_tokens,
            )

    findings = filter_findings(
        findings,
        confidence_threshold=config.review.confidence_threshold,
        max_comments=config.review.max_comments,
    )

    # Without a model call nothing was reviewed, so there's no verdict to give.
    reviewed = reviewer_model is not None and bool(reviewed_files) and over_budget is None
    base_lines = _base_lines(
        pr_number, pull_request, filenames, _verdict(findings) if reviewed else None
    )
    warning_lines = (
        (["", NO_REVIEWER_NOTICE] if reviewer_model is None else [])
        + _config_change_lines(filenames, base_sha)
        + _budget_warning_lines(over_budget)
        + _redaction_warning_lines(redacted_files)
        + coverage_lines
    )
    if output_format == "text":
        print(
            "\n".join(
                base_lines + warning_lines + [line for f in findings for line in _finding_lines(f)]
            )
        )

    comment_posted = False
    if comment:
        patches = {str(file["filename"]): file.get("patch") for file in files}
        try:
            reviews = client.list_reviews(pr_number)
            posted = posted_fingerprints(
                [review.get("body") for review in reviews]
                + [c.get("body") for c in review_comments]
            )
            new_findings = [f for f in findings if not _nearby_fingerprints(f, patches) & posted]
            if len(new_findings) < len(findings):
                print(
                    f"marginal review: skipped {len(findings) - len(new_findings)} finding(s) "
                    "matching one already posted on this PR (same file and severity, same or "
                    "neighbouring line)",
                    file=sys.stderr,
                )
            already_reviewed = any(REVIEW_HEADING in (r.get("body") or "") for r in reviews)
            if new_findings or not already_reviewed or over_budget is not None:
                verdict = _verdict(new_findings, already_posted=len(findings) - len(new_findings))
                body = "\n".join(
                    _base_lines(pr_number, pull_request, filenames, verdict if reviewed else None)
                    + warning_lines
                    + [
                        line
                        for f in new_findings
                        if not _anchorable(f, patches)
                        for line in [
                            *_finding_lines(f),
                            fingerprint_marker(_fingerprint(f, patches)),
                        ]
                    ]
                )
                client.create_review(
                    pr_number,
                    body,
                    event="COMMENT",
                    comments=_build_inline_comments(
                        [f for f in new_findings if _anchorable(f, patches)], patches
                    ),
                )
                comment_posted = True
            else:
                print(
                    "marginal review: nothing new since marginal's last review on this PR, "
                    "so nothing was posted",
                    file=sys.stderr,
                )
        except (PermissionDeniedError, GitHubAuthenticationError, GitHubAPIError) as exc:
            print(f"marginal review: {exc}", file=sys.stderr)
            return 1
        # Each later push also re-checks what marginal flagged before; only a
        # resolved finding gets anything posted.
        if already_reviewed and reviewed:
            _close_resolved_findings(
                client,
                reviewer_model,
                config.review.max_prompt_tokens,
                pr_number,
                files,
                review_comments,
            )

    if output_format == "json":
        result = _build_json_result(
            repo,
            pr_number,
            pull_request,
            filenames,
            findings,
            redacted_files,
            comment_posted=comment_posted,
            prompt_over_budget=over_budget is not None,
        )
        print(json.dumps(result, indent=2))

    return 0


def _load_base_config(
    client: GitHubClient, pull_request: dict[str, object], path: str
) -> tuple[MarginalConfig, str | None]:
    """`.marginal/config.yaml` as of the PR's base commit, and that commit.

    When the base has no config yet -- the PR that first sets marginal up --
    falls back to the one under `path` and returns `None` for the commit.
    """
    base_sha = str(pull_request["base"]["sha"])
    text = client.get_file(CONFIG_RELATIVE_PATH.as_posix(), base_sha)
    if text is None:
        return load_config(path), None
    return parse_config(text, f"{CONFIG_RELATIVE_PATH.as_posix()} at {base_sha[:7]}"), base_sha


def _load_base_policies(
    client: GitHubClient, base_sha: str | None, path: str, policy_paths: list[str]
) -> list[tuple[str, str]]:
    """`policy_paths` as of `base_sha`, like `load_policies` reads them under `path`."""
    if base_sha is None:
        return load_policies(path, policy_paths)
    policies = []
    for policy_path in policy_paths:
        # The contents API 404s on `./x`, which a local read accepted.
        content = client.get_file(PurePosixPath(policy_path).as_posix(), base_sha)
        if content is None:
            print(
                f"marginal review: warning: policy file not found, skipping: {policy_path}",
                file=sys.stderr,
            )
            continue
        policies.append((policy_path, content))
    return policies


def _config_change_lines(filenames: list[str], base_sha: str | None) -> list[str]:
    """Say so when the PR edits `.marginal/`, since this review didn't use its edits."""
    if base_sha is None or not any(name.startswith(".marginal/") for name in filenames):
        return []
    return [
        "",
        "ℹ️ This PR changes `.marginal/`. Review settings and policies come from the base "
        "branch, so the changes apply after it merges.",
    ]


def _skip_reason(review: ReviewConfig, pull_request: dict[str, object]) -> str | None:
    """Why `--comment` should post nothing for `pull_request`, or `None`."""
    if not review.enabled:
        return "review.enabled is false"
    if review.skip_drafts and pull_request.get("draft"):
        return "the PR is a draft (review.skip_drafts)"
    user = pull_request.get("user") or {}
    if review.skip_bots and user.get("type") == "Bot":
        return f"the PR was opened by a bot, {user.get('login')} (review.skip_bots)"
    # GitHub label names are case-insensitive.
    labels = {label["name"].casefold() for label in pull_request.get("labels") or []}
    for label in review.skip_labels:
        if label.casefold() in labels:
            return f"the PR has the `{label}` label (review.skip_labels)"
    return None


def _close_resolved_findings(
    client: GitHubClient,
    model_spec: ModelSpec,
    max_prompt_tokens: int,
    pr_number: int,
    files: list[dict[str, object]],
    review_comments: list[dict[str, object]],
) -> None:
    """Best-effort `marginal compact --comment` for a re-review: logs one line
    to stderr and never fails the review or touches stdout."""
    # Imported here: `marginal.cli.compact` imports helpers from this module.
    from marginal.cli.compact import CompactSkipped, _is_closed, close_resolved_findings

    try:
        findings, verdicts = close_resolved_findings(
            client,
            model_spec,
            pr_number,
            files,
            review_comments,
            client.list_review_threads(pr_number),
            client.list_issue_comments(pr_number),
            max_prompt_tokens=max_prompt_tokens,
            post=True,
            log_prefix="marginal review",
        )
    except (CompactSkipped, ProviderError, GitHubError) as exc:
        print(f"marginal review: couldn't re-check earlier findings: {exc}", file=sys.stderr)
        return
    if findings:
        resolved = sum(1 for v in verdicts.values() if _is_closed(v))
        print(
            f"marginal review: re-checked {len(findings)} earlier finding(s): "
            f"{resolved} resolved, {len(findings) - resolved} still open",
            file=sys.stderr,
        )


def _base_lines(
    pr_number: int | None,
    pull_request: dict[str, object],
    filenames: list[str],
    verdict: str | None = None,
) -> list[str]:
    """Render the review header: the `verdict` line (if any), a title line,
    and a collapsed file list.

    The verdict leads so the outcome is readable without opening a single
    inline thread. The file list sits behind a `<details>` block so it
    doesn't dominate the review on larger PRs -- expanding it is one click,
    not a wall of text.
    """
    file_word = "file" if len(filenames) == 1 else "files"
    lines = [REVIEW_HEADING, ""]
    if verdict is not None:
        lines += [verdict, ""]
    base_sha = str(pull_request["base"]["sha"])[:7]
    head_sha = str(pull_request["head"]["sha"])[:7]
    if pr_number is None:
        repo = pull_request["base"]["repo"]["full_name"]
        lines.append(f"**{repo} {base_sha}...{head_sha}** · {len(filenames)} {file_word} changed")
    else:
        lines.append(
            f"**PR #{pr_number}: {pull_request['title']}** · {pull_request['state']} · "
            f"`{base_sha}` → `{head_sha}` · {len(filenames)} {file_word} changed"
        )
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


def _verdict(findings: list[Finding], *, already_posted: int = 0) -> str:
    """One line summing up a review's findings by severity, most serious first,
    e.g. `**3 findings** · 🔴 1 critical · 🟠 2 high`, or that there were none.

    `already_posted` counts findings left out because an earlier run on this
    PR already flagged them, so "nothing new" isn't read as "nothing wrong".
    """
    if findings:
        counts = Counter(finding.severity for finding in findings)
        noun = "finding" if len(findings) == 1 else "findings"
        verdict = f"**{len(findings)} {noun}** · " + " · ".join(
            f"{emoji} {counts[severity]} {severity.value}"
            for severity, emoji in SEVERITY_EMOJI.items()
            if counts[severity]
        )
    else:
        verdict = "✅ **No new issues**" if already_posted else "✅ **No issues found**"
    if already_posted:
        verdict += f" · {already_posted} already flagged earlier on this PR"
    return verdict


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


def _redaction_warning_lines(redacted_files: list[str]) -> list[str]:
    """Render a warning naming `redacted_files`, or `[]` if none were redacted.

    Folded into the same review body as the header and findings rather than
    a second comment -- `marginal review --comment` posts exactly one
    `create_review` per run, so this rides along with it.
    """
    if not redacted_files:
        return []
    files_list = ", ".join(f"`{filename}`" for filename in redacted_files)
    return [
        "",
        f"⚠️ **Redacted a likely secret** in {files_list} before this diff reached "
        "the review model -- rotate it if it was real.",
    ]


def _build_inline_comments(
    findings: list[Finding], patches: dict[str, str | None]
) -> list[dict[str, object]]:
    """Build one GitHub review `comments` entry per line-anchored finding.

    A finding with no `line` is left out here -- callers should fall back to
    including it in the review's overall body instead, so it isn't silently
    dropped. The comment's own file/line already anchors it in the diff, so
    its badge skips repeating the location. Each body ends with the
    finding's hidden fingerprint marker, so a later run can skip it.
    """
    return [
        {
            "path": finding.file,
            "line": finding.line,
            "body": f"{_finding_badge(finding, with_location=False)}\n\n{finding.message}"
            f"\n\n{fingerprint_marker(_fingerprint(finding, patches))}",
        }
        for finding in findings
        if finding.line is not None
    ]


def _anchorable(finding: Finding, patches: dict[str, str | None]) -> bool:
    """Whether GitHub accepts an inline comment at `finding`'s line: it must
    fall inside one of its file's diff hunks. GitHub rejects the whole review
    (422) over a single comment anchored anywhere else, so such a finding goes
    in the review body instead."""
    patch = patches.get(finding.file)
    return (
        finding.line is not None
        and bool(patch)
        and any(start <= finding.line <= end for start, end in _hunk_ranges(str(patch)))
    )


def _fingerprint(finding: Finding, patches: dict[str, str | None]) -> str:
    return finding_fingerprint(*_identity(finding, patches))


def _nearby_fingerprints(finding: Finding, patches: dict[str, str | None]) -> set[str]:
    return nearby_fingerprints(*_identity(finding, patches))


def _identity(
    finding: Finding, patches: dict[str, str | None]
) -> tuple[str, int | None, str, str, str | None]:
    return (
        finding.file,
        finding.line,
        finding.severity.value,
        finding.message,
        patches.get(finding.file),
    )


def _build_json_result(
    repo: str,
    pr_number: int | None,
    pull_request: dict[str, object],
    filenames: list[str],
    findings: list[Finding],
    redacted_files: list[str],
    *,
    comment_posted: bool,
    prompt_over_budget: bool,
) -> dict[str, object]:
    """Build the `--format json` payload for one review run.

    Carries the same information the text summary surfaces -- PR metadata,
    the changed-file list, the surviving `findings` (each dumped via
    `Finding.model_dump(mode="json")`, so `severity` comes out as its plain
    string value rather than the `Severity` enum member) and `redacted_files`
    -- plus `comment_posted`, which the text summary never states explicitly,
    and `prompt_over_budget`, true when the model was never called because the
    prompt exceeded `review.max_prompt_tokens` (so empty `findings` mean
    "not reviewed", not "nothing found").
    A finding's `line` being `None` means what it does for
    `_build_inline_comments`. Reviewing two commits (`pr_number=None`) leaves
    `title` and `state` `None`.
    """
    is_pr = pr_number is not None
    return {
        "repo": repo,
        "pr_number": pr_number,
        "title": str(pull_request["title"]) if is_pr else None,
        "state": str(pull_request["state"]) if is_pr else None,
        "base_sha": str(pull_request["base"]["sha"]),
        "head_sha": str(pull_request["head"]["sha"]),
        "changed_files": filenames,
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "redacted_files": redacted_files,
        "comment_posted": comment_posted,
        "prompt_over_budget": prompt_over_budget,
    }


async def _generate_findings(
    model_spec: ModelSpec,
    files: list[dict[str, object]],
    policies: list[tuple[str, str]],
    graph_context: list[ChangedDefinition],
    repo_root: str,
    replies: list[ReplyThread],
    *,
    max_prompt_tokens: int,
    anti_policies: list[tuple[str, str]] | None = None,
) -> list[Finding]:
    """Generate a bounded list of unvalidated `Finding`s from `model_spec` over
    `files`' diffs, `policies`, `graph_context`, maintainer `replies`, and
    `anti_policies`.

    Raises `_PromptOverBudget` without touching the provider if the built
    prompt is estimated over `max_prompt_tokens`. The check runs on the final
    prompt string, so every section the builder adds counts toward the cap.
    """
    prompt = _build_finding_prompt(
        files, policies, graph_context, repo_root, replies, anti_policies
    )
    estimated_tokens = _estimate_tokens(prompt)
    if estimated_tokens > max_prompt_tokens:
        raise _PromptOverBudget(
            f"the review prompt is an estimated {estimated_tokens:,} tokens, over "
            f"review.max_prompt_tokens ({max_prompt_tokens:,}), so no model was called"
        )
    provider = get_provider(model_spec)
    result = await provider.generate_structured(prompt, schema=_FindingsResponse)
    if not isinstance(result, _FindingsResponse):
        raise ProviderResponseError(
            f"expected a _FindingsResponse from generate_structured, got {type(result).__name__}"
        )
    return result.findings


def _estimate_tokens(text: str) -> int:
    """Rough token count for `text`. Exact counts are provider- and
    model-specific; this only needs to catch prompts far beyond normal size."""
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


def _budget_warning_lines(over_budget: _PromptOverBudget | None) -> list[str]:
    """Render a warning that generation was skipped for size, or `[]`.

    First among the warnings: with no model call, nothing in the diff was
    reviewed, so the empty findings list must not read as a clean bill.
    """
    if over_budget is None:
        return []
    return ["", f"⚠️ **Review skipped** -- {over_budget}, so nothing in this diff was reviewed."]


def _build_graph_context(
    repo_root: str, files: list[dict[str, object]], *, enabled: bool
) -> list[ChangedDefinition]:
    """The PR's changed definitions and their out-of-diff callers, or `[]`.

    `[]` both when `enabled` is `False` and when building the graph fails for
    any reason (`repo_root` isn't a git working tree, `git` isn't installed,
    a tracked file has invalid syntax) -- this context is a best-effort
    addition to the prompt, never something that should fail the review
    itself, the same way a missing policy file only warns rather than
    aborting.
    """
    if not enabled:
        return []
    try:
        graph = build_symbol_graph(repo_root)
        return find_out_of_diff_callers(graph, files)
    except Exception as exc:
        print(
            f"marginal review: warning: couldn't build code-graph context, skipping: {exc}",
            file=sys.stderr,
        )
        return []


def _missing_patch_filenames(files: list[dict[str, object]]) -> list[str]:
    """Filenames GitHub returned with no patch content.

    GitHub omits a file's `patch` entirely once its diff is too large or
    it's binary -- the file still appears in the files list, but there's no
    diff for `_build_finding_prompt` to include, so it was never reviewed.
    """
    return [str(file["filename"]) for file in files if not file.get("patch")]


def _is_ignored(filename: str, patterns: Sequence[str]) -> bool:
    """Whether `filename` matches a `review.ignore_paths` pattern: one with no
    `/` against the file name alone, otherwise against the whole path."""
    name = filename.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(filename if "/" in p else name, p) for p in patterns)


def _ignored_lines(count: int) -> list[str]:
    """Name how many changed files `review.ignore_paths` kept from the model."""
    if not count:
        return []
    return [
        "",
        f"ℹ️ **{count} file(s) not reviewed** -- they match `review.ignore_paths`.",
    ]


def _coverage_warning_lines(
    pull_request: dict[str, object],
    files: list[dict[str, object]],
    ignore_paths: Sequence[str] = (),
) -> list[str]:
    """Warn about any gap between what changed in `pull_request` and what
    `files` actually gave the reviewer model something to look at.

    Two independent gaps, each optional: `pull_request["changed_files"]`
    (when GitHub reports it) exceeding `len(files)` means GitHub's own
    3000-file-per-PR cap truncated the file list; a file present in `files`
    but missing its `patch` means that file's diff never reached the model.
    Neither is fatal -- both just get named so a review's silence about a
    file isn't mistaken for "nothing to flag there."
    """
    lines: list[str] = []
    changed_files = pull_request.get("changed_files")
    if isinstance(changed_files, int) and changed_files > len(files):
        lines += [
            "",
            f"⚠️ **Incomplete review coverage** -- reviewed {len(files)} of "
            f"{changed_files} changed files; GitHub did not return the rest.",
        ]
    # An ignored file was never going to be reviewed, so its missing patch isn't a gap.
    missing_patch = [
        name for name in _missing_patch_filenames(files) if not _is_ignored(name, ignore_paths)
    ]
    if missing_patch:
        files_list = ", ".join(f"`{filename}`" for filename in missing_patch)
        lines += [
            "",
            f"⚠️ **No diff available** for {files_list} -- GitHub omitted the patch "
            "(large diff or binary file), so this file wasn't reviewed.",
        ]
    return lines


def _redact_patches(files: list[dict[str, object]]) -> list[dict[str, object]]:
    """`files` with each `patch` run through `redact_secrets` -- once per run."""
    return [{**file, "patch": redact_secrets(str(file.get("patch", "")))} for file in files]


def _redacted_filenames(
    files: list[dict[str, object]], redacted: list[dict[str, object]]
) -> list[str]:
    """Filenames whose patch `_redact_patches` changed, i.e. masked a likely secret."""
    return [
        str(file["filename"])
        for file, clean in zip(files, redacted, strict=True)
        if clean["patch"] != str(file.get("patch", ""))
    ]


def _build_finding_prompt(
    files: list[dict[str, object]],
    policies: list[tuple[str, str]],
    graph_context: list[ChangedDefinition],
    repo_root: str,
    replies: list[ReplyThread] | None = None,
    anti_policies: list[tuple[str, str]] | None = None,
) -> str:
    """The reviewer prompt. `files` must already be `_redact_patches` output."""
    diff = "\n\n".join(f"--- {file['filename']} ---\n{file['patch']}" for file in files)
    sections = [FINDING_PROMPT_INSTRUCTIONS]
    if policies:
        policy_text = "\n\n".join(f"--- {path} ---\n{content}" for path, content in policies)
        sections.append(
            "Also weigh the diff against this repository's own engineering policies "
            "below -- a violation of one of these is at least as important as a "
            f"general code-quality issue:\n\n{policy_text}"
        )
    if anti_policies:
        anti_policy_text = "\n\n".join(
            f"--- {path} ---\n{content}" for path, content in anti_policies
        )
        sections.append(
            "Never flag anything that this repository's anti-policies below describe "
            "-- each is a deliberate, accepted decision the maintainers don't want "
            "raised in review. Leave such issues out of your findings entirely, even "
            f"if they would otherwise look like a problem:\n\n{anti_policy_text}"
        )
    graph_section = _build_graph_context_section(graph_context, repo_root)
    if graph_section:
        sections.append(graph_section)
    if replies:
        sections.append(_build_replies_section(replies))
    sections.append(diff)
    return "\n\n".join(sections)


def _build_graph_context_section(
    graph_context: list[ChangedDefinition], repo_root: str
) -> str | None:
    """A prompt section naming out-of-diff callers of what this diff changes.

    `None` if there's nothing to show -- `graph_context` is empty, every
    changed definition's callers are all inside the diff already, or none of
    the caller files could be read for a snippet. Bounded to
    `MAX_GRAPH_CONTEXT_CALLERS` caller snippets total, across every changed
    definition, so a definition with a huge fan-out can't blow up the prompt.
    """
    blocks: list[str] = []
    remaining = MAX_GRAPH_CONTEXT_CALLERS
    for changed in graph_context:
        if remaining <= 0:
            break
        caller_blocks = []
        for site in changed.callers:
            if len(caller_blocks) >= remaining:
                break
            snippet = _read_snippet(repo_root, site.file, site.line)
            if snippet is not None:
                caller_blocks.append(f"{site.file}:{site.line}\n{snippet}")
        if not caller_blocks:
            continue
        remaining -= len(caller_blocks)
        blocks.append(
            f"`{changed.definition.qualified_name}` (defined in "
            f"{changed.definition.file}) is called from:\n\n" + "\n\n".join(caller_blocks)
        )
    if not blocks:
        return None
    return (
        "This diff changes definitions that other, unchanged files in the repo call -- "
        "check whether the change is compatible with how they're used there:\n\n"
        + "\n\n".join(blocks)
    )


def _build_replies_section(replies: list[ReplyThread]) -> str:
    """A prompt section quoting maintainer answers to marginal's earlier comments.

    Keeps the `MAX_REPLY_THREADS` most recent threads, clips each comment and
    its replies, and runs the result through `redact_secrets` -- the text is
    human-written, but may still quote code from the diff.
    """
    blocks = []
    for thread in replies[-MAX_REPLY_THREADS:]:
        location = thread.path if thread.line is None else f"{thread.path}:{thread.line}"
        reply_text = "\n\n".join(thread.replies)
        blocks.append(
            f"--- {location} ---\n"
            f"marginal's earlier comment:\n{_clip(thread.comment, _REPLY_COMMENT_CHARS)}\n\n"
            f"Maintainer reply:\n{_clip(reply_text, _REPLY_TEXT_CHARS)}"
        )
    return redact_secrets(
        "A maintainer already answered some of marginal's earlier comments on this pull "
        "request. Don't raise any of these points again -- reworded, or on a nearby line -- "
        "unless the code it's about has changed in a way the reply doesn't cover:\n\n"
        + "\n\n".join(blocks)
    )


def _clip(text: str, limit: int) -> str:
    """`text`, cut to `limit` characters with a ` [...]` mark if it was longer."""
    return text if len(text) <= limit else text[:limit].rstrip() + " [...]"


def _read_snippet(repo_root: str, file: str, line: int) -> str | None:
    """A few lines of `file` around `line` (1-indexed), secrets redacted, or
    `None` if unreadable. The file is outside the diff, so nothing else
    redacts it before it reaches the model."""
    try:
        lines = Path(repo_root, file).read_text().splitlines()
    except OSError:
        return None
    start = max(line - _GRAPH_CONTEXT_SNIPPET_RADIUS, 1)
    end = min(line + _GRAPH_CONTEXT_SNIPPET_RADIUS, len(lines))
    return redact_secrets("\n".join(f"{n}: {lines[n - 1]}" for n in range(start, end + 1)))
