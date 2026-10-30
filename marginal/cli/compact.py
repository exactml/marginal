"""`marginal compact`: re-check marginal's open findings on a PR, close stale ones."""

from __future__ import annotations

import asyncio
import sys

from marginal.config.errors import ConfigError
from marginal.config.schema import ModelSpec, PermissionsConfig
from marginal.context import load_base_config
from marginal.github.client import GitHubClient
from marginal.github.errors import GitHubError
from marginal.providers.errors import MissingCredentialsError, ProviderError, ProviderResponseError
from marginal.providers.factory import get_provider
from marginal.review.dedup import _MARKER
from marginal.review.prompt import RECHECK_INSTRUCTIONS, estimate_tokens
from marginal.review.redact import redact_patches, redact_secrets
from marginal.review.replies import RESOLVED_MARKER, is_marginal_comment
from marginal.review.schema import Recheck, RecheckResponse

COMPACT_HEADING = "### 🧹 marginal compact"

# Characters kept from each person's comment quoted in the re-check prompt.
_ANSWER_CHARS = 600


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
    # From the PR's base commit, like `marginal review`: the PR can't change it.
    base_client = GitHubClient(repo, PermissionsConfig())
    try:
        config, _ = load_base_config(base_client, base_client.get_pull_request(pr_number), path)
    except ConfigError as exc:
        print(f"marginal compact: {exc}", file=sys.stderr)
        return 1
    except GitHubError as exc:
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
        issue_comments = client.list_issue_comments(pr_number)
    except GitHubError as exc:
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
            issue_comments,
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
    except (ProviderError, GitHubError) as exc:
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
    issue_comments: list[dict[str, object]],
    *,
    max_prompt_tokens: int,
    post: bool,
    log_prefix: str,
) -> tuple[list[dict[str, object]], dict[object, Recheck]]:
    """Re-check marginal's open findings and, with `post`, close the resolved ones.

    Returns the open findings and the verdict for each one the model (or the
    file-left-the-diff rule) answered. A finding is closed when the current
    code no longer has the problem, or when a person's comment disputes it:
    the model matches each finding against the human replies in its thread
    and the human PR comments (`issue_comments`) posted after it, and a
    dismissal is only kept if it names one of those comments. A finding still
    open gets nothing posted. Raises `CompactSkipped` over budget, `ProviderError` from the
    model, and GitHub errors from posting a reply; a failed thread resolve is
    only reported on stderr under `log_prefix`. Shared by `marginal compact`
    and `marginal review --comment`'s re-check on later pushes.
    """
    # A thread someone already resolved in GitHub's UI counts as closed too.
    closed_by_hand = {t["comment_id"] for t in threads if t["is_resolved"]}
    thread_ids = {t["comment_id"]: t["id"] for t in threads}
    if post:
        # marginal already replied "Resolved" but the thread is still open: an
        # earlier resolve failed (an Actions token without `contents: write`).
        roots = {c["id"]: c for c in comments}
        for comment_id in _resolved_by_reply(comments) - closed_by_hand:
            if comment_id in thread_ids and comment_id in roots:
                _resolve_thread(client, thread_ids[comment_id], roots[comment_id], log_prefix)
    findings = [c for c in _open_findings(comments) if c["id"] not in closed_by_hand]
    if not findings:
        return [], {}

    patches = {str(f["filename"]): str(f["patch"]) for f in redact_patches(files)}
    verdicts = {
        c["id"]: Recheck(
            id=c["id"], still_applies=False, reason="its file is no longer changed by this PR"
        )
        for c in findings
        if c.get("path") not in patches
    }
    to_check = [c for c in findings if c["id"] not in verdicts]
    answers = _answers(to_check, comments, issue_comments)
    if to_check:
        prompt = _build_recheck_prompt(to_check, patches, answers)
        estimated_tokens = estimate_tokens(prompt)
        if estimated_tokens > max_prompt_tokens:
            raise CompactSkipped(
                f"the prompt is an estimated {estimated_tokens:,} tokens, over "
                f"review.max_prompt_tokens ({max_prompt_tokens:,}), so no model was called"
            )
        results = asyncio.run(_recheck(model_spec, prompt))
        for r in results:
            if r.id not in answers:
                continue
            # Only a person's comment this finding was shown with can dismiss it.
            if r.dismissed_by not in {a["id"] for a in answers[r.id]}:
                r = r.model_copy(update={"dismissed_by": None})
            verdicts[r.id] = r

    if post:
        by_id = {a["id"]: a for found in answers.values() for a in found}
        for c in findings:
            verdict = verdicts.get(c["id"])
            if verdict is None or not _is_closed(verdict):
                continue
            client.reply_to_review_comment(
                pr_number,
                c["id"],
                f"✅ **Resolved**: {_resolution(verdict, by_id)}\n\n{RESOLVED_MARKER}",
            )
            if c["id"] in thread_ids:
                _resolve_thread(client, thread_ids[c["id"]], c, log_prefix)
    return findings, verdicts


def _resolved_by_reply(comments: list[dict[str, object]]) -> set[object]:
    """Ids of the findings whose thread already has marginal's resolution reply."""
    return {
        c.get("in_reply_to_id") for c in comments if RESOLVED_MARKER in str(c.get("body") or "")
    }


def _resolve_thread(
    client: GitHubClient, thread_id: str, comment: dict[str, object], log_prefix: str
) -> None:
    """Best-effort: the reply already records the resolution, so a token that
    can't resolve threads costs only the collapse, not the run."""
    try:
        client.resolve_review_thread(thread_id)
    except GitHubError as exc:
        print(
            f"{log_prefix}: replied on {_location(comment)} but couldn't resolve its thread "
            f"(in GitHub Actions the job needs `permissions: contents: write`): {exc}",
            file=sys.stderr,
        )


def _open_findings(comments: list[dict[str, object]]) -> list[dict[str, object]]:
    """marginal's own inline findings whose thread has no resolution reply yet."""
    closed = _resolved_by_reply(comments)
    return [
        c
        for c in comments
        if not c.get("in_reply_to_id")
        and c["id"] not in closed
        and is_marginal_comment(str(c.get("body") or ""))
    ]


def _build_recheck_prompt(
    findings: list[dict[str, object]],
    patches: dict[str, str],
    answers: dict[object, list[dict[str, object]]],
) -> str:
    """The instructions, each finding with its id, location and its thread's
    human replies, then the other human PR comments, then the current diff of
    every file those findings are in (each file once)."""
    blocks = []
    for c in findings:
        replies = [a for a in answers[c["id"]] if a.get("in_reply_to_id") == c["id"]]
        blocks.append(
            "\n".join(
                [
                    f"--- finding {c['id']} at {_location(c)} ---",
                    _MARKER.sub("", str(c.get("body") or "")).strip(),
                    *(_quote(a, "reply") for a in replies),
                ]
            )
        )
    shared = {
        a["id"]: a for found in answers.values() for a in found if not a.get("in_reply_to_id")
    }
    others = ["Other pull request comments:", *(_quote(a, "comment") for a in shared.values())]
    diffs = [
        f"--- {file} ---\n{patches[file]}" for file in dict.fromkeys(c["path"] for c in findings)
    ]
    return "\n\n".join(
        [RECHECK_INSTRUCTIONS, *blocks, *(others if shared else []), "Current diff:", *diffs]
    )


def _answers(
    findings: list[dict[str, object]],
    comments: list[dict[str, object]],
    issue_comments: list[dict[str, object]],
) -> dict[object, list[dict[str, object]]]:
    """For each finding, the people's comments that could answer it: human
    replies in its own thread, and human PR comments posted after it."""
    people = [c for c in issue_comments if _is_person(c)]
    return {
        f["id"]: [c for c in comments if c.get("in_reply_to_id") == f["id"] and _is_person(c)]
        + [c for c in people if str(c.get("created_at") or "") > str(f.get("created_at") or "")]
        for f in findings
    }


def _is_person(comment: dict[str, object]) -> bool:
    body = str(comment.get("body") or "").strip()
    user = comment.get("user") or {}
    return bool(body) and user.get("type") != "Bot" and not is_marginal_comment(body)


def _quote(comment: dict[str, object], kind: str) -> str:
    login = (comment.get("user") or {}).get("login", "someone")
    text = redact_secrets(str(comment.get("body") or "").strip())
    if len(text) > _ANSWER_CHARS:
        text = text[:_ANSWER_CHARS].rstrip() + " [...]"
    return f"{kind} {comment['id']} by @{login}: {text}"


def _is_closed(verdict: Recheck) -> bool:
    return not verdict.still_applies or verdict.dismissed_by is not None


def _resolution(verdict: Recheck, by_id: dict[object, dict[str, object]]) -> str:
    """Why a closed finding is closed: who dismissed it, or the code change."""
    if verdict.dismissed_by is None:
        return verdict.reason
    comment = by_id[verdict.dismissed_by]
    login = (comment.get("user") or {}).get("login", "someone")
    first_line = str(comment.get("body") or "").strip().splitlines()[0]
    quote = first_line if len(first_line) <= 120 else first_line[:117].rstrip() + "..."
    return f'@{login} says this isn\'t an issue ("{quote}"), so marginal is closing it.'


async def _recheck(model_spec: ModelSpec, prompt: str) -> list[Recheck]:
    provider = get_provider(model_spec)
    result = await provider.generate_structured(prompt, schema=RecheckResponse)
    if not isinstance(result, RecheckResponse):
        raise ProviderResponseError(
            f"expected a RecheckResponse from generate_structured, got {type(result).__name__}"
        )
    return result.results


def _summary_lines(
    pr_number: int, findings: list[dict[str, object]], verdicts: dict[object, Recheck]
) -> list[str]:
    resolved = sum(1 for c in findings if c["id"] in verdicts and _is_closed(verdicts[c["id"]]))
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
        elif verdict.dismissed_by is not None:
            lines.append(
                f"- ✅ `{_location(c)}`: dismissed in comment {verdict.dismissed_by}. "
                f"{verdict.reason}"
            )
        elif verdict.still_applies:
            lines.append(f"- ⏳ `{_location(c)}`: still applies. {verdict.reason}")
        else:
            lines.append(f"- ✅ `{_location(c)}`: resolved. {verdict.reason}")
    return lines


def _location(comment: dict[str, object]) -> str:
    # An outdated comment (its line pushed out of the diff) keeps `original_line`.
    line = comment.get("line") or comment.get("original_line")
    return f"{comment.get('path')}:{line}" if line else str(comment.get("path"))
