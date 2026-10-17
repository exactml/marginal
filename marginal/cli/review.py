"""Fetch and summarize a pull request: `marginal review`."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from marginal.config.loader import load_config
from marginal.config.schema import ModelSpec
from marginal.github.client import GitHubClient
from marginal.github.errors import GitHubAPIError, GitHubAuthenticationError, PermissionDeniedError
from marginal.graph import ChangedDefinition, build_symbol_graph, find_out_of_diff_callers
from marginal.policy import load_policies
from marginal.providers.errors import MissingCredentialsError, ProviderError, ProviderResponseError
from marginal.providers.factory import get_provider
from marginal.review import Finding, Severity, filter_findings
from marginal.review.redact import redact_secrets

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


class _FindingsResponse(BaseModel):
    """Structured-output wrapper: the bounded list of findings for one review."""

    model_config = ConfigDict(extra="forbid")

    findings: list[Finding] = Field(max_length=MAX_FINDINGS_PER_REVIEW)


def run_review(repo: str, pr_number: int, path: str = ".", *, comment: bool = False) -> int:
    """Fetch `pr_number` from `repo` and print a plain-text summary.

    Loads `.marginal/config.yaml` under `path` and builds a `GitHubClient`
    gated by its `permissions`, then fetches the pull request's metadata and
    changed files and prints its title, state, base/head SHA, and the
    changed file list (collapsed behind a Markdown `<details>` block so it
    doesn't dominate the output on larger PRs).

    If `models.reviewer` is configured, also generates a bounded list of
    unvalidated, structured `Finding`s (up to `MAX_FINDINGS_PER_REVIEW`) from
    that model over the changed files' diffs -- each file's patch run
    through `marginal.review.redact_secrets` first, so a diff containing a
    recognizable secret shape never reaches the model with that value intact
    -- plus the content of any `config.policies` files (loaded via
    `marginal.policy.load_policies`, relative to `path`; a missing file is
    skipped with a warning rather than failing the review), then runs the
    list through `marginal.review.filter_findings`: each finding is dropped
    outright if its self-reported `confidence` is below
    `config.review.confidence_threshold`, and the survivors are capped at
    `config.review.max_comments` (highest-confidence first). Each finding
    that survives appends to the printed summary as a severity+confidence
    badge (e.g. `🔴 **Critical** · 92% confidence`) followed by its message.
    Without `models.reviewer`, or if every finding gets filtered out, the
    summary stays metadata-only, same as if nothing was generated.

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

    Returns 0 on success. A denied permission, missing/invalid token,
    GitHub API error, or `ProviderError` — whether raised while fetching,
    generating a finding, or (with `comment` set) posting — is caught here,
    printed as a single line to stderr, and turned into exit code 1 instead
    of propagating as a raw traceback. The one exception is a configured
    reviewer missing its required credentials (`MissingCredentialsError`),
    which exits 3 instead of 1 -- distinct enough for a caller (like
    `marginal-action`) to tell "needs fixing" apart from "expected, e.g. a
    forked PR that never got the secret" and react differently.
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
    findings: list[Finding] = []
    redacted_files: list[str] = []
    coverage_lines: list[str] = []
    if reviewer_model is not None:
        policies = load_policies(path, config.policies)
        redacted_files = _redacted_filenames(files)
        coverage_lines = _coverage_warning_lines(pull_request, files)
        graph_context = _build_graph_context(path, files, enabled=config.context.code_graph)
        try:
            findings = asyncio.run(
                _generate_findings(reviewer_model, files, policies, graph_context, path)
            )
        except MissingCredentialsError as exc:
            print(f"marginal review: {exc}", file=sys.stderr)
            return 3
        except ProviderError as exc:
            print(f"marginal review: {exc}", file=sys.stderr)
            return 1

    findings = filter_findings(
        findings,
        confidence_threshold=config.review.confidence_threshold,
        max_comments=config.review.max_comments,
    )
    inline_comments = _build_inline_comments(findings)

    base_lines = _base_lines(pr_number, pull_request, filenames)
    warning_lines = _redaction_warning_lines(redacted_files) + coverage_lines
    summary = "\n".join(
        base_lines + warning_lines + [line for f in findings for line in _finding_lines(f)]
    )
    print(summary)

    if comment:
        body = "\n".join(
            base_lines
            + warning_lines
            + [line for f in findings if f.line is None for line in _finding_lines(f)]
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


async def _generate_findings(
    model_spec: ModelSpec,
    files: list[dict[str, object]],
    policies: list[tuple[str, str]],
    graph_context: list[ChangedDefinition],
    repo_root: str,
) -> list[Finding]:
    """Generate a bounded list of unvalidated `Finding`s from `model_spec` over
    `files`' diffs, `policies`, and `graph_context`."""
    provider = get_provider(model_spec)
    prompt = _build_finding_prompt(files, policies, graph_context, repo_root)
    result = await provider.generate_structured(prompt, schema=_FindingsResponse)
    if not isinstance(result, _FindingsResponse):
        raise ProviderResponseError(
            f"expected a _FindingsResponse from generate_structured, got {type(result).__name__}"
        )
    return result.findings


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


def _coverage_warning_lines(
    pull_request: dict[str, object], files: list[dict[str, object]]
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
    missing_patch = _missing_patch_filenames(files)
    if missing_patch:
        files_list = ", ".join(f"`{filename}`" for filename in missing_patch)
        lines += [
            "",
            f"⚠️ **No diff available** for {files_list} -- GitHub omitted the patch "
            "(large diff or binary file), so this file wasn't reviewed.",
        ]
    return lines


def _redacted_filenames(files: list[dict[str, object]]) -> list[str]:
    """Filenames whose patch contains a likely secret that `redact_secrets` masked."""
    return [
        str(file["filename"])
        for file in files
        if redact_secrets(patch := str(file.get("patch", ""))) != patch
    ]


def _build_finding_prompt(
    files: list[dict[str, object]],
    policies: list[tuple[str, str]],
    graph_context: list[ChangedDefinition],
    repo_root: str,
) -> str:
    diff = "\n\n".join(
        f"--- {file['filename']} ---\n{redact_secrets(str(file.get('patch', '')))}"
        for file in files
    )
    sections = [FINDING_PROMPT_INSTRUCTIONS]
    if policies:
        policy_text = "\n\n".join(f"--- {path} ---\n{content}" for path, content in policies)
        sections.append(
            "Also weigh the diff against this repository's own engineering policies "
            "below -- a violation of one of these is at least as important as a "
            f"general code-quality issue:\n\n{policy_text}"
        )
    graph_section = _build_graph_context_section(graph_context, repo_root)
    if graph_section:
        sections.append(graph_section)
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


def _read_snippet(repo_root: str, file: str, line: int) -> str | None:
    """A few lines of `file` around `line` (1-indexed), or `None` if unreadable."""
    try:
        lines = Path(repo_root, file).read_text().splitlines()
    except OSError:
        return None
    start = max(line - _GRAPH_CONTEXT_SNIPPET_RADIUS, 1)
    end = min(line + _GRAPH_CONTEXT_SNIPPET_RADIUS, len(lines))
    return "\n".join(f"{n}: {lines[n - 1]}" for n in range(start, end + 1))
