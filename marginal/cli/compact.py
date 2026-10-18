"""`marginal compact`: re-check marginal's open findings on a PR, close stale ones."""

from __future__ import annotations

import asyncio
import sys

from pydantic import BaseModel, ConfigDict

from marginal.cli.review import _estimate_tokens, _redact_patches
from marginal.config.errors import ConfigError
from marginal.config.loader import load_config
from marginal.config.schema import ModelSpec
from marginal.github.client import GitHubClient
from marginal.github.errors import GitHubAPIError, GitHubAuthenticationError, PermissionDeniedError
from marginal.providers.errors import MissingCredentialsError, ProviderError, ProviderResponseError
from marginal.providers.factory import get_provider
from marginal.review.dedup import _MARKER
from marginal.review.replies import RESOLVED_MARKER, is_marginal_comment

COMPACT_HEADING = "### 🧹 marginal compact"

RECHECK_INSTRUCTIONS = (
    "You previously posted the review findings below on this pull request. The "
    "pull request has changed since. For each finding, decide from the current "
    "diff of its file whether the problem it describes is still present. Answer "
    "still_applies=false only if the current code clearly no longer has the "
    "problem (it was fixed, or the code was removed); if you're unsure, answer "
    "true. Give a one-sentence reason either way, and return one result per "
    "finding id."
)

_GITHUB_ERRORS = (PermissionDeniedError, GitHubAuthenticationError, GitHubAPIError)


class _Recheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    still_applies: bool
    reason: str


class _RecheckResponse(BaseModel):
    """Structured-output wrapper: one verdict per re-checked finding."""

    model_config = ConfigDict(extra="forbid")

    results: list[_Recheck]


def run_compact(repo: str, pr_number: int, path: str = ".", *, comment: bool = False) -> int:
    """Re-check marginal's still-open inline findings on `pr_number` against
    the PR's current diff, and print which are resolved.

    An open finding is one of marginal's own inline comments (fingerprint
    marker or severity badge) whose thread has no earlier resolution reply. A
    finding whose file the PR no longer changes is resolved outright; the rest
    go to `models.reviewer` in one call, which keeps a finding open unless the
    current diff clearly no longer has the problem. A finding the model leaves
    out of its answer stays open.

    With `comment`, each resolved finding gets a reply in its thread ending in
    `RESOLVED_MARKER`, so a later run skips it, and its thread is resolved
    (collapsed in GitHub's UI). A failure to resolve is reported but doesn't
    fail the run. A thread already resolved by hand counts as closed. Without
    `comment`, nothing is posted.
    A PR with no open findings is a no-op that never calls the model.

    Errors follow `marginal review`'s contract: one stderr line and exit 1,
    or exit 3 when the reviewer's credentials are missing. A prompt over
    `review.max_prompt_tokens` re-checks nothing and exits 0.
    """
    try:
        config = load_config(path)
    except ConfigError as exc:
        print(f"marginal compact: {exc}", file=sys.stderr)
        return 1
    reviewer_model = config.models.get("reviewer")
    if reviewer_model is None:
        print(
            "marginal compact: needs models.reviewer in .marginal/config.yaml to re-check findings",
            file=sys.stderr,
        )
        return 1
    client = GitHubClient(repo, config.permissions)

    try:
        files = client.get_pull_request_files(pr_number)
        comments = client.list_review_comments(pr_number)
        threads = client.list_review_threads(pr_number)
    except _GITHUB_ERRORS as exc:
        print(f"marginal compact: {exc}", file=sys.stderr)
        return 1

    try:
        findings, verdicts = close_resolved_findings(
            client,
            reviewer_model,
            pr_number,
            files,
            comments,
            threads,
            max_prompt_tokens=config.review.max_prompt_tokens,
            post=comment,
            log_prefix="marginal compact",
        )
    except CompactSkipped as exc:
        print(f"marginal compact: skipped re-checking: {exc}", file=sys.stderr)
        return 0
    except MissingCredentialsError as exc:
        print(f"marginal compact: {exc}", file=sys.stderr)
        return 3
    except (ProviderError, *_GITHUB_ERRORS) as exc:
        print(f"marginal compact: {exc}", file=sys.stderr)
        return 1

    if not findings:
        print(f"{COMPACT_HEADING}\n\nNo open marginal findings on PR #{pr_number}.")
    else:
        print("\n".join(_summary_lines(pr_number, findings, verdicts)))
    return 0


class CompactSkipped(Exception):
    """The re-check prompt is over `review.max_prompt_tokens`; no model was called."""


def close_resolved_findings(
    client: GitHubClient,
    model_spec: ModelSpec,
    pr_number: int,
    files: list[dict[str, object]],
    comments: list[dict[str, object]],
    threads: list[dict[str, object]],
    *,
    max_prompt_tokens: int,
    post: bool,
    log_prefix: str,
) -> tuple[list[dict[str, object]], dict[object, _Recheck]]:
    """Re-check marginal's open findings and, with `post`, close the resolved ones.

    Returns the open findings and the verdict for each one the model (or the
    file-left-the-diff rule) answered. A finding still open gets nothing
    posted. Raises `CompactSkipped` over budget, `ProviderError` from the
    model, and GitHub errors from posting a reply; a failed thread resolve is
    only reported on stderr under `log_prefix`. Shared by `marginal compact`
    and `marginal review --comment`'s re-check on later pushes.
    """
    # A thread someone already resolved in GitHub's UI counts as closed too.
    closed_by_hand = {t["comment_id"] for t in threads if t["is_resolved"]}
    thread_ids = {t["comment_id"]: t["id"] for t in threads}
    findings = [c for c in _open_findings(comments) if c["id"] not in closed_by_hand]
    if not findings:
        return [], {}

    patches = {str(f["filename"]): str(f["patch"]) for f in _redact_patches(files)}
    verdicts = {
        c["id"]: _Recheck(
            id=c["id"], still_applies=False, reason="its file is no longer changed by this PR"
        )
        for c in findings
        if c.get("path") not in patches
    }
    to_check = [c for c in findings if c["id"] not in verdicts]
    if to_check:
        prompt = _build_recheck_prompt(to_check, patches)
        estimated_tokens = _estimate_tokens(prompt)
        if estimated_tokens > max_prompt_tokens:
            raise CompactSkipped(
                f"the prompt is an estimated {estimated_tokens:,} tokens, over "
                f"review.max_prompt_tokens ({max_prompt_tokens:,}), so no model was called"
            )
        results = asyncio.run(_recheck(model_spec, prompt))
        asked = {c["id"] for c in to_check}
        verdicts.update({r.id: r for r in results if r.id in asked})

    if post:
        for c in findings:
            if c["id"] not in verdicts or verdicts[c["id"]].still_applies:
                continue
            client.reply_to_review_comment(
                pr_number,
                c["id"],
                f"✅ **Resolved**: {verdicts[c['id']].reason}\n\n{RESOLVED_MARKER}",
            )
            # Best-effort: the reply already records the resolution, so a token
            # that can't resolve threads costs only the collapse, not the run.
            try:
                if c["id"] in thread_ids:
                    client.resolve_review_thread(thread_ids[c["id"]])
            except _GITHUB_ERRORS as exc:
                print(
                    f"{log_prefix}: replied on {_location(c)} but couldn't resolve "
                    f"its thread: {exc}",
                    file=sys.stderr,
                )
    return findings, verdicts


def _open_findings(comments: list[dict[str, object]]) -> list[dict[str, object]]:
    """marginal's own inline findings whose thread has no resolution reply yet."""
    closed = {
        c.get("in_reply_to_id") for c in comments if RESOLVED_MARKER in str(c.get("body") or "")
    }
    return [
        c
        for c in comments
        if not c.get("in_reply_to_id")
        and c["id"] not in closed
        and is_marginal_comment(str(c.get("body") or ""))
    ]


def _build_recheck_prompt(findings: list[dict[str, object]], patches: dict[str, str]) -> str:
    """The instructions, each finding with its id and location, then the
    current diff of every file those findings are in (each file once)."""
    blocks = [
        f"--- finding {c['id']} at {_location(c)} ---\n"
        f"{_MARKER.sub('', str(c.get('body') or '')).strip()}"
        for c in findings
    ]
    diffs = [
        f"--- {file} ---\n{patches[file]}" for file in dict.fromkeys(c["path"] for c in findings)
    ]
    return "\n\n".join([RECHECK_INSTRUCTIONS, *blocks, "Current diff:", *diffs])


async def _recheck(model_spec: ModelSpec, prompt: str) -> list[_Recheck]:
    provider = get_provider(model_spec)
    result = await provider.generate_structured(prompt, schema=_RecheckResponse)
    if not isinstance(result, _RecheckResponse):
        raise ProviderResponseError(
            f"expected a _RecheckResponse from generate_structured, got {type(result).__name__}"
        )
    return result.results


def _summary_lines(
    pr_number: int, findings: list[dict[str, object]], verdicts: dict[object, _Recheck]
) -> list[str]:
    resolved = sum(
        1 for c in findings if c["id"] in verdicts and not verdicts[c["id"]].still_applies
    )
    lines = [
        COMPACT_HEADING,
        "",
        f"**PR #{pr_number}**: re-checked {len(findings)} open finding(s) · "
        f"✅ {resolved} resolved · ⏳ {len(findings) - resolved} still open",
        "",
    ]
    for c in findings:
        verdict = verdicts.get(c["id"])
        if verdict is None:
            lines.append(f"- ⏳ `{_location(c)}`: no answer from the model, left open")
        elif verdict.still_applies:
            lines.append(f"- ⏳ `{_location(c)}`: still applies. {verdict.reason}")
        else:
            lines.append(f"- ✅ `{_location(c)}`: resolved. {verdict.reason}")
    return lines


def _location(comment: dict[str, object]) -> str:
    # An outdated comment (its line pushed out of the diff) keeps `original_line`.
    line = comment.get("line") or comment.get("original_line")
    return f"{comment.get('path')}:{line}" if line else str(comment.get("path"))
