"""Machine-readable review output: the `--format json` payload."""

from __future__ import annotations

from marginal.review.evidence import Decision
from marginal.review.render import comment_span
from marginal.review.schema import Finding


def build_json_result(
    repo: str,
    pr_number: int | None,
    pull_request: dict[str, object],
    filenames: list[str],
    findings: list[Finding],
    redacted_files: list[str],
    *,
    comment_posted: bool,
    prompt_over_budget: bool,
    dropped: list[Decision],
    patches: dict[str, str | None],
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
    `build_inline_comments`; one posted across several lines also carries
    the `start_line` and `end_line` its comment spans (`comment_span`). Reviewing
    two commits (`pr_number=None`) leaves `title` and `state` `None`. Every
    finding, posted or not, carries the `checks` marginal ran on it;
    `dropped_findings` are the ones the posting rule or `review.max_comments`
    kept off the PR, each with its `reason`.
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
        "findings": [_finding_json(finding, patches) for finding in findings],
        "dropped_findings": [
            _finding_json(d.finding, patches) | {"reason": d.reason} for d in dropped
        ],
        "redacted_files": redacted_files,
        "comment_posted": comment_posted,
        "prompt_over_budget": prompt_over_budget,
    }


def _finding_json(finding: Finding, patches: dict[str, str | None]) -> dict[str, object]:
    data = finding.model_dump(mode="json")
    span = comment_span(finding, patches)
    if span is not None and span[0] < span[1]:
        data["start_line"], data["end_line"] = span
    checks = finding.checks
    if checks is not None:
        for item, verified in zip(data["evidence"], checks.quotes, strict=False):
            item["verified"] = verified
        data["checks"] = {
            "quotes_verified": checks.quotes_verified,
            "quotes_not_found": checks.quotes_not_found,
            "trigger_concrete": checks.trigger_concrete,
            "caller_shown": checks.caller_shown,
        }
    return data
