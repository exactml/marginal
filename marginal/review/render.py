"""Render a review as Markdown: the verdict, finding badges, inline
comments, and the warning lines that name what wasn't reviewed."""

from __future__ import annotations

import fnmatch
from collections import Counter
from collections.abc import Sequence

from marginal.graph.diff import _hunk_ranges
from marginal.review.dedup import fingerprint_marker, fingerprint_of
from marginal.review.prompt import PromptOverBudget
from marginal.review.redact import redact_secrets
from marginal.review.schema import Finding, Severity

SEVERITY_EMOJI = {
    Severity.CRITICAL: "🔴",
    Severity.HIGH: "🟠",
    Severity.MEDIUM: "🟡",
    Severity.LOW: "⚪",
}


# A posted finding widens to its verified quotes this close to its own line;
# a quote further away is context, not the code the comment is about.
_MAX_SPAN_DISTANCE = 10


# Every review marginal posts opens with this, which is how a re-run spots
# that it has already reviewed a PR.
REVIEW_HEADING = "### 🤖 marginal review"


# Shown when no model reviewed the diff; without it, a fresh `marginal init`
# setup posts just a title and file list with nothing pointing at the gap.
NO_REVIEWER_NOTICE = (
    "ℹ️ **No reviewer model configured**, so only the PR's metadata is shown. Set "
    "`models.reviewer` in `.marginal/config.yaml` to have a model review the diff."
)


def config_change_lines(filenames: list[str], base_sha: str | None) -> list[str]:
    """Say so when the PR edits `.marginal/`, since this review didn't use its edits."""
    if base_sha is None or not any(name.startswith(".marginal/") for name in filenames):
        return []
    return [
        "",
        "ℹ️ This PR changes `.marginal/`. Review settings and policies come from the base "
        "branch, so the changes apply after it merges.",
    ]


def header_lines(
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


def verdict_line(findings: list[Finding], *, already_posted: int = 0) -> str:
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


_SEVERITY_LABELS = {f"marginal:{severity.value}" for severity in Severity}


def severity_labels(findings: list[Finding]) -> list[str]:
    """One `marginal:<severity>` label per severity among `findings`, most
    serious first. The fixed prefix keeps marginal off labels it doesn't own."""
    present = {finding.severity for finding in findings}
    return [f"marginal:{severity.value}" for severity in SEVERITY_EMOJI if severity in present]


def stale_severity_labels(pull_request: dict[str, object], wanted: list[str]) -> list[str]:
    """The severity labels on `pull_request` that aren't in `wanted` -- a
    severity no finding still earns. Any other label, even one starting
    `marginal:`, isn't marginal's."""
    names = [str(label["name"]) for label in pull_request.get("labels") or []]
    return [name for name in names if name in _SEVERITY_LABELS and name not in wanted]


def finding_badge(finding: Finding, *, with_location: bool) -> str:
    """Render a finding's severity as one line, e.g. `🔴 **Critical**` --
    optionally suffixed with its file location, for contexts (like a review's
    overall body) that aren't already anchored to that location the way an
    inline comment is.
    """
    badge = f"{SEVERITY_EMOJI[finding.severity]} **{finding.severity.value.title()}**"
    if with_location:
        location = finding.file if finding.line is None else f"{finding.file}:{finding.line}"
        badge += f" — `{location}`"
    return badge


def finding_lines(finding: Finding) -> list[str]:
    """Render one `Finding` as its badge, message and "Why" block, each its
    own paragraph."""
    badge = finding_badge(finding, with_location=True)
    return ["", badge, "", finding.message, *why_lines(finding)]


def why_lines(finding: Finding) -> list[str]:
    """A folded "Why marginal flagged this" block: the trigger, each verified
    quote, and the assumptions. Model-written text goes through
    `redact_secrets`, like everything else marginal posts."""
    checks = finding.checks
    if checks is None:
        return []
    verified = [e for e, ok in zip(finding.evidence, checks.quotes, strict=False) if ok]
    lines = ["", "<details><summary>Why marginal flagged this</summary>", ""]
    if finding.trigger:
        lines.append(f"- **Trigger:** {redact_secrets(finding.trigger)}")
    if verified:
        lines.append(
            "- **Evidence:** "
            + " · ".join(f"`{e.file}:{e.line}` {_code_span(e.quote)} ✓" for e in verified)
        )
    if finding.assumptions:
        lines.append("- **Assumed:** " + "; ".join(redact_secrets(a) for a in finding.assumptions))
    return [*lines, "", "</details>"]


def _code_span(text: str) -> str:
    text = redact_secrets(" ".join(text.split()))
    return f"`` {text} ``" if "`" in text else f"`{text}`"


def redaction_warning_lines(redacted_files: list[str]) -> list[str]:
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


def build_inline_comments(
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
            **_span_fields(comment_span(finding, patches)),
            "body": "\n".join(
                [
                    finding_badge(finding, with_location=False),
                    "",
                    finding.message,
                    *why_lines(finding),
                    "",
                    fingerprint_marker(fingerprint_of(finding, patches)),
                ]
            ),
        }
        for finding in findings
        if finding.line is not None
    ]


def anchorable(finding: Finding, patches: dict[str, str | None]) -> bool:
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


def comment_span(finding: Finding, patches: dict[str, str | None]) -> tuple[int, int] | None:
    """The lines `finding` covers: its own line widened to its verified quotes
    in the same diff hunk, at most `_MAX_SPAN_DISTANCE` lines away. GitHub
    accepts a multi-line comment only within one hunk. `None` without a line."""
    if finding.line is None:
        return None
    line = finding.line
    hunks = _hunk_ranges(str(patches.get(finding.file) or ""))
    hunk = next((h for h in hunks if h[0] <= line <= h[1]), None)
    checks = finding.checks
    if hunk is None or checks is None:
        return line, line
    quoted = [
        e.line
        for e, verified in zip(finding.evidence, checks.quotes, strict=False)
        if verified
        and e.file == finding.file
        and hunk[0] <= e.line <= hunk[1]
        and abs(e.line - line) <= _MAX_SPAN_DISTANCE
    ]
    return min([line, *quoted]), max([line, *quoted])


def _span_fields(span: tuple[int, int] | None) -> dict[str, int | None]:
    """A review comment's `line`, plus `start_line` when it spans more than one."""
    if span is None:
        return {"line": None}
    start, end = span
    return {"start_line": start, "line": end} if start < end else {"line": end}


def budget_warning_lines(over_budget: PromptOverBudget | None) -> list[str]:
    """Render a warning that generation was skipped for size, or `[]`.

    First among the warnings: with no model call, nothing in the diff was
    reviewed, so the empty findings list must not read as a clean bill.
    """
    if over_budget is None:
        return []
    return ["", f"⚠️ **Review skipped** -- {over_budget}, so nothing in this diff was reviewed."]


def missing_patch_filenames(files: list[dict[str, object]]) -> list[str]:
    """Filenames GitHub returned with no patch content.

    GitHub omits a file's `patch` entirely once its diff is too large or
    it's binary -- the file still appears in the files list, but there's no
    diff for `build_finding_prompt` to include, so it was never reviewed.
    """
    return [str(file["filename"]) for file in files if not file.get("patch")]


def is_ignored(filename: str, patterns: Sequence[str]) -> bool:
    """Whether `filename` matches a `review.ignore_paths` pattern: one with no
    `/` against the file name alone, otherwise against the whole path."""
    name = filename.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(filename if "/" in p else name, p) for p in patterns)


def ignored_lines(count: int) -> list[str]:
    """Name how many changed files `review.ignore_paths` kept from the model."""
    if not count:
        return []
    return [
        "",
        f"ℹ️ **{count} file(s) not reviewed** -- they match `review.ignore_paths`.",
    ]


def coverage_warning_lines(
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
        name for name in missing_patch_filenames(files) if not is_ignored(name, ignore_paths)
    ]
    if missing_patch:
        files_list = ", ".join(f"`{filename}`" for filename in missing_patch)
        lines += [
            "",
            f"⚠️ **No diff available** for {files_list} -- GitHub omitted the patch "
            "(large diff or binary file), so this file wasn't reviewed.",
        ]
    return lines
