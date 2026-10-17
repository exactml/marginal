"""Find maintainer replies to marginal's own inline comments on a PR.

When a maintainer answers one of marginal's findings ("intentional, here's
why"), the next run on the same PR otherwise has no memory of it and tends to
raise the same point again in new words. GitHub's review-comment threads are
already the durable store for that answer, so this reads them back.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from marginal.review.dedup import _MARKER

# The severity+confidence badge every marginal finding opens with. Releases
# before the fingerprint marker existed posted findings with only this, so
# it's the one way to recognize those older comments as marginal's own.
_BADGE = re.compile(r"^(?:🔴|🟠|🟡|⚪) \*\*(?:Critical|High|Medium|Low)\*\* · \d+% confidence")


@dataclass(frozen=True)
class ReplyThread:
    """One of marginal's inline comments and the maintainer replies to it."""

    path: str
    line: int | None
    comment: str
    replies: tuple[str, ...]


def is_marginal_comment(body: str | None) -> bool:
    """Whether `body` is a finding marginal posted: it carries the
    fingerprint marker, or opens with marginal's severity badge."""
    return bool(body) and bool(_MARKER.search(body) or _BADGE.match(body))


def maintainer_replies(comments: Iterable[dict[str, object]]) -> list[ReplyThread]:
    """Threads under marginal's inline comments that a person replied to.

    `comments` is GitHub's list of a PR's review comments, oldest first; a
    reply's `in_reply_to_id` always names its thread's first comment. Replies
    under anyone else's comment, replies posted by a bot account, and
    anything that is itself a marginal finding are left out, so only human
    answers to marginal come back. Threads keep GitHub's order, oldest first.
    """
    comments = list(comments)
    roots = {
        c["id"]: c
        for c in comments
        if c.get("id") is not None and not c.get("in_reply_to_id") and is_marginal_comment(_body(c))
    }
    replies: dict[object, list[str]] = {}
    for c in comments:
        parent = c.get("in_reply_to_id")
        body = _body(c).strip()
        user = c.get("user") or {}
        if (
            parent in roots
            and body
            and not is_marginal_comment(body)
            and isinstance(user, dict)
            and user.get("type") != "Bot"
        ):
            replies.setdefault(parent, []).append(body)
    return [
        ReplyThread(
            path=str(root.get("path", "")),
            # An outdated comment (its line pushed out of the diff) has
            # `line: null` but keeps `original_line`.
            line=root.get("line") or root.get("original_line"),
            comment=_MARKER.sub("", _body(root)).strip(),
            replies=tuple(replies[root_id]),
        )
        for root_id, root in roots.items()
        if root_id in replies
    ]


def _body(comment: dict[str, object]) -> str:
    return str(comment.get("body") or "")
