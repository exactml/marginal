"""Fetch and summarize a pull request: `marginal review`."""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from typing import Literal, get_args

from marginal.config.errors import ConfigError
from marginal.config.schema import MarginalConfig, ModelSpec, PermissionsConfig, ReviewConfig
from marginal.context import (
    build_graph_context,
    load_base_config,
    load_base_policies,
    read_ci_conclusion,
)
from marginal.github.client import GitHubClient
from marginal.github.errors import GitHubError
from marginal.graph import ChangedDefinition
from marginal.providers.base import reset_usage, usage
from marginal.providers.errors import MissingCredentialsError, ProviderError, ProviderResponseError
from marginal.providers.factory import get_provider
from marginal.review import Finding
from marginal.review.dedup import (
    current_fingerprints,
    fingerprint_marker,
    fingerprint_of,
    nearby_fingerprints_of,
    posted_fingerprints,
)
from marginal.review.evidence import OVER_MAX_COMMENTS, CodeView, Decision, decide
from marginal.review.output import build_json_result
from marginal.review.prompt import (
    PromptOverBudget,
    build_finding_prompt,
    build_graph_context_section,
    estimate_tokens,
)
from marginal.review.redact import redact_patches, redacted_filenames
from marginal.review.render import (
    NO_REVIEWER_NOTICE,
    REVIEW_HEADING,
    anchorable,
    budget_warning_lines,
    build_inline_comments,
    config_change_lines,
    coverage_warning_lines,
    finding_lines,
    header_lines,
    ignored_lines,
    is_ignored,
    redaction_warning_lines,
    severity_labels,
    stale_severity_labels,
    verdict_line,
)
from marginal.review.replies import ReplyThread, maintainer_replies
from marginal.review.schema import FindingsResponse

OutputFormat = Literal["text", "json"]


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
    policy files as of the PR's base commit (`load_base_config`), so the PR
    can't change the rules it's reviewed by; only when the base has no config
    yet does it fall back to the one under `path`. It builds a `GitHubClient`
    gated by that config's `permissions` and fetches the changed files.
    With the default `output_format="text"`, prints its
    title, state, base/head SHA, and the changed file list (collapsed behind
    a Markdown `<details>` block so it doesn't dominate the output on larger
    PRs).

    With `output_format="json"`, prints the object built by
    `marginal.review.output.build_json_result` instead. `--format` only changes what reaches
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
    want re-litigated. Then it checks each finding and applies the posting
    rule (`marginal.review.evidence.decide`), with no further model call: a
    finding is posted only if at least one of its quoted lines is found at its
    line (within a couple of lines) and its trigger names code from the diff or
    the caller context; the rest are dropped with a reason. Posted findings are
    capped at `config.review.max_comments`, most severe first. Each one appends
    to the printed summary as a severity badge (e.g. `🔴 **Critical**`), its
    message, and a folded "Why marginal flagged this" block with its trigger,
    verified quotes and assumptions. Without `models.reviewer`, or if every
    finding is dropped, the summary stays metadata-only, same as if nothing
    was generated.

    Before any model call, the fully built prompt's size is estimated
    (`marginal.review.prompt.estimate_tokens`, a length heuristic) and checked against
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
    minified assets by default; see `is_ignored`) stay in the file list but
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
    silently dropped. With `permissions.write.labels` on, the PR also gets a
    `marginal:<severity>` label for each severity among the findings that
    survived (`GitHubClient.add_labels`), and loses any other `marginal:` label
    (`GitHubClient.remove_label`); a failure there only logs a line to stderr.
    Omitting `--comment` posts nothing back to GitHub.

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
    reset_usage()

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
        config, base_sha, policies, anti_policies = _load_rules(base_client, pull_request, path)
    except (ConfigError, GitHubError) as exc:
        print(f"marginal review: {exc}", file=sys.stderr)
        return 1
    reviewer_model = config.models.get("reviewer")
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
    except GitHubError as exc:
        print(f"marginal review: {exc}", file=sys.stderr)
        return 1

    # Only with `--comment`, so a draft can still be previewed locally.
    skip_reason = _skip_reason(config.review, pull_request) if comment else None
    if skip_reason is not None:
        print(f"marginal review: skipped, nothing posted -- {skip_reason}", file=sys.stderr)
        return 0

    filenames = [str(file["filename"]) for file in files]
    ignore_paths = config.review.ignore_paths
    reviewed_files = [f for f in files if not is_ignored(str(f["filename"]), ignore_paths)]
    coverage_lines: list[str] = []
    if reviewer_model is not None:
        coverage_lines = ignored_lines(len(files) - len(reviewed_files))
        coverage_lines += coverage_warning_lines(pull_request, files, ignore_paths)

    try:
        findings, dropped, redacted_files, over_budget = _review_files(
            client,
            config,
            pull_request,
            reviewed_files,
            review_comments,
            path,
            policies,
            anti_policies,
        )
    except MissingCredentialsError as exc:
        print(f"marginal review: {exc}", file=sys.stderr)
        return 3
    except ProviderError as exc:
        print(f"marginal review: {exc}", file=sys.stderr)
        return 1

    # Without a model call nothing was reviewed, so there's no verdict to give.
    reviewed = reviewer_model is not None and bool(reviewed_files) and over_budget is None
    warning_lines = (
        (["", NO_REVIEWER_NOTICE] if reviewer_model is None else [])
        + config_change_lines(filenames, base_sha)
        + budget_warning_lines(over_budget)
        + redaction_warning_lines(redacted_files)
        + coverage_lines
    )
    if output_format == "text":
        print(
            "\n".join(
                header_lines(
                    pr_number, pull_request, filenames, verdict_line(findings) if reviewed else None
                )
                + warning_lines
                + [line for f in findings for line in finding_lines(f)]
            )
        )

    patches = {str(file["filename"]): file.get("patch") for file in files}
    comment_posted = False
    if comment:
        try:
            comment_posted, already_reviewed = _post_review(
                client,
                pr_number,
                pull_request,
                filenames,
                findings,
                warning_lines,
                review_comments,
                patches,
                reviewed=reviewed,
                over_budget=over_budget is not None,
            )
        except GitHubError as exc:
            print(f"marginal review: {exc}", file=sys.stderr)
            return 1
        if config.permissions.write.labels:
            _update_labels(client, pr_number, pull_request, findings, dropped, reviewed=reviewed)
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
        result = build_json_result(
            repo,
            pr_number,
            pull_request,
            filenames,
            findings,
            redacted_files,
            comment_posted=comment_posted,
            prompt_over_budget=over_budget is not None,
            dropped=dropped,
            patches=patches,
        )
        # Summed over every model call above: findings, its retry, the re-check.
        model = f"{reviewer_model.provider}:{reviewer_model.model}" if reviewer_model else None
        result["usage"] = {"model": model, **usage()}
        print(json.dumps(result, indent=2))

    return 0


def _load_rules(
    client: GitHubClient, pull_request: dict[str, object], path: str
) -> tuple[MarginalConfig, str | None, list[tuple[str, str]], list[tuple[str, str]]]:
    """The config, the base commit it came from, and its policies and
    anti-policies, which are only read when a reviewer model will use them."""
    config, base_sha = load_base_config(client, pull_request, path)
    if config.models.get("reviewer") is None:
        return config, base_sha, [], []
    policies = load_base_policies(client, base_sha, path, config.policies)
    anti_policies = load_base_policies(client, base_sha, path, config.anti_policies)
    return config, base_sha, policies, anti_policies


def _review_files(
    client: GitHubClient,
    config: MarginalConfig,
    pull_request: dict[str, object],
    files: list[dict[str, object]],
    review_comments: list[dict[str, object]],
    path: str,
    policies: list[tuple[str, str]],
    anti_policies: list[tuple[str, str]],
) -> tuple[list[Finding], list[Decision], list[str], PromptOverBudget | None]:
    """Have the reviewer model review `files`, then check what it found.

    Returns the findings to post, the dropped ones with their reason, the
    files whose diff had a likely secret redacted, and the over-budget error
    if the prompt was too big to send. Nothing happens without a reviewer
    model or when every changed file is ignored. Raises `ProviderError`.
    """
    reviewer_model = config.models.get("reviewer")
    if reviewer_model is None or not files:
        return [], [], [], None
    redacted = redact_patches(files)
    redacted_files = redacted_filenames(files, redacted)
    graph_context = build_graph_context(path, files, enabled=config.context.code_graph)
    try:
        findings = asyncio.run(
            _generate_findings(
                reviewer_model,
                redacted,
                policies,
                graph_context,
                path,
                maintainer_replies(review_comments),
                max_prompt_tokens=config.review.max_prompt_tokens,
                anti_policies=anti_policies,
                ci_conclusion=read_ci_conclusion(
                    client, config.permissions, str(pull_request["head"]["sha"])
                ),
            )
        )
    except PromptOverBudget as exc:
        print(
            f"marginal review: skipped generating findings: {exc} -- raise the cap in "
            ".marginal/config.yaml or split the PR to review it",
            file=sys.stderr,
        )
        return [], [], redacted_files, exc
    if not findings:
        return [], [], redacted_files, None

    # Checked against what the model was shown: the (redacted) diff and the
    # caller context, plus the rest of each file from the checkout.
    context = build_graph_context_section(graph_context, path) or ""
    decisions = decide(
        findings, CodeView(path, redacted, context), max_comments=config.review.max_comments
    )
    dropped = [d for d in decisions if not d.posted]
    if dropped:
        reasons = Counter(d.reason for d in dropped)
        print(
            f"marginal review: dropped {len(dropped)} finding(s): "
            + ", ".join(f"{count} {reason}" for reason, count in reasons.most_common()),
            file=sys.stderr,
        )
    return [d.finding for d in decisions if d.posted], dropped, redacted_files, None


def _post_review(
    client: GitHubClient,
    pr_number: int,
    pull_request: dict[str, object],
    filenames: list[str],
    findings: list[Finding],
    warning_lines: list[str],
    review_comments: list[dict[str, object]],
    patches: dict[str, str | None],
    *,
    reviewed: bool,
    over_budget: bool,
) -> tuple[bool, bool]:
    """Post the review, leaving out findings already posted on this PR.

    Posts nothing when there's nothing new and marginal already reviewed the
    PR, unless the prompt was over budget. Returns whether it posted, and
    whether marginal had reviewed this PR before. Raises `GitHubError`.
    """
    reviews = client.list_reviews(pr_number)
    posted = posted_fingerprints(
        [review.get("body") for review in reviews] + [c.get("body") for c in review_comments]
    )
    posted |= current_fingerprints(review_comments, patches)
    new_findings = [f for f in findings if not nearby_fingerprints_of(f, patches) & posted]
    if len(new_findings) < len(findings):
        print(
            f"marginal review: skipped {len(findings) - len(new_findings)} finding(s) "
            "matching one already posted on this PR (same file and severity, same or "
            "neighbouring line)",
            file=sys.stderr,
        )
    already_reviewed = any(REVIEW_HEADING in (r.get("body") or "") for r in reviews)
    if not (new_findings or not already_reviewed or over_budget):
        print(
            "marginal review: nothing new since marginal's last review on this PR, "
            "so nothing was posted",
            file=sys.stderr,
        )
        return False, already_reviewed
    verdict = verdict_line(new_findings, already_posted=len(findings) - len(new_findings))
    body = "\n".join(
        header_lines(pr_number, pull_request, filenames, verdict if reviewed else None)
        + warning_lines
        + [
            line
            for f in new_findings
            if not anchorable(f, patches)
            for line in [*finding_lines(f), fingerprint_marker(fingerprint_of(f, patches))]
        ]
    )
    client.create_review(
        pr_number,
        body,
        event="COMMENT",
        comments=build_inline_comments(
            [f for f in new_findings if anchorable(f, patches)], patches
        ),
    )
    return True, already_reviewed


def _update_labels(
    client: GitHubClient,
    pr_number: int,
    pull_request: dict[str, object],
    findings: list[Finding],
    dropped: list[Decision],
    *,
    reviewed: bool,
) -> None:
    """Add a `marginal:<severity>` label per severity found, and remove the
    ones no finding earns any more. Labels only add triage signal, so failing
    to add or remove one never fails the review."""
    wanted = severity_labels(findings)
    if wanted:
        try:
            client.add_labels(pr_number, wanted)
        except GitHubError as exc:
            print(f"marginal review: couldn't add labels: {exc}", file=sys.stderr)
    # Without a review there are no current findings to judge a label by,
    # and a finding capped by `review.max_comments` is still there.
    if reviewed:
        capped = [d.finding for d in dropped if d.reason == OVER_MAX_COMMENTS]
        kept = severity_labels(findings + capped)
        for name in stale_severity_labels(pull_request, kept):
            try:
                client.remove_label(pr_number, name)
            except GitHubError as exc:
                print(f"marginal review: couldn't remove label {name}: {exc}", file=sys.stderr)


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
    ci_conclusion: str | None = None,
) -> list[Finding]:
    """Generate a bounded list of unvalidated `Finding`s from `model_spec` over
    `files`' diffs, `policies`, `graph_context`, maintainer `replies`,
    `anti_policies`, and the triggering CI run's `ci_conclusion`.

    Raises `PromptOverBudget` without touching the provider if the built
    prompt is estimated over `max_prompt_tokens`. The check runs on the final
    prompt string, so every section the builder adds counts toward the cap.
    """
    prompt = build_finding_prompt(
        files, policies, graph_context, repo_root, replies, anti_policies, ci_conclusion
    )
    estimated_tokens = estimate_tokens(prompt)
    if estimated_tokens > max_prompt_tokens:
        raise PromptOverBudget(
            f"the review prompt is an estimated {estimated_tokens:,} tokens, over "
            f"review.max_prompt_tokens ({max_prompt_tokens:,}), so no model was called"
        )
    provider = get_provider(model_spec)
    result = await provider.generate_structured(prompt, schema=FindingsResponse)
    if not isinstance(result, FindingsResponse):
        raise ProviderResponseError(
            f"expected a FindingsResponse from generate_structured, got {type(result).__name__}"
        )
    return result.findings
