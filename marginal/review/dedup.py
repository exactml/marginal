"""Fingerprint posted findings so a re-run doesn't post the same one twice.

GitHub's own comment bodies are the store: each posted finding carries a
hidden `<!-- marginal:finding:<hash> -->` marker, and a re-run skips any
finding whose hash is already present on the PR.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from marginal.review.redact import redact_secrets

_MARKER = re.compile(r"<!-- marginal:finding:([0-9a-f]{16}) -->")
_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def finding_fingerprint(
    file: str, line: int | None, severity: str, message: str, patch: str | None
) -> str:
    """A stable 16-hex-char identity for a finding, for dedup across runs.

    The model rewords the same issue on every run, so a line-anchored
    finding is identified by its file, severity and the *text* of the line it
    points at (read from `patch`) -- not by its message, and not by its line
    number either, so a push that only shifts lines above it still matches.
    If the line isn't in `patch`, its number stands in for its text. A
    finding with no line falls back to its whitespace/case-normalized
    message, which rarely matches across runs -- the cost of that is a
    repeat, never a dropped finding.
    """
    if line is None:
        anchor = "message:" + " ".join(message.lower().split())
    else:
        text = _new_line_text(patch, line)
        anchor = f"text:{text}" if text is not None else f"line:{line}"
    return hashlib.sha256(f"{file}\0{severity}\0{anchor}".encode()).hexdigest()[:16]


def nearby_fingerprints(
    file: str, line: int | None, severity: str, message: str, patch: str | None
) -> set[str]:
    """The fingerprints a finding counts as a repeat of, if already posted.

    The model's line anchor drifts by one between runs (the same issue
    pinned to the line above on one run, its own line on the next), so a
    line-anchored finding also matches a same-severity one posted on either
    neighbouring line. A genuinely new issue right next to an old one of the
    same severity is therefore treated as a repeat.
    """
    if line is None:
        return {finding_fingerprint(file, None, severity, message, patch)}
    return {
        finding_fingerprint(file, nearby, severity, message, patch)
        for nearby in (line - 1, line, line + 1)
    }


def fingerprint_marker(fingerprint: str) -> str:
    """The hidden HTML comment embedded in a posted finding's body."""
    return f"<!-- marginal:finding:{fingerprint} -->"


def posted_fingerprints(bodies: Iterable[str | None]) -> set[str]:
    """Every fingerprint marker found in `bodies` (comment/review texts)."""
    return {match for body in bodies if body for match in _MARKER.findall(body)}


def _new_line_text(patch: str | None, line: int) -> str | None:
    """The whitespace-normalized text of new-file `line` in `patch`, if shown.

    Run through `redact_secrets` first, so the hash never derives from a
    secret value.
    """
    if not patch:
        return None
    current = None
    for raw in redact_secrets(patch).splitlines():
        header = _HUNK_HEADER.match(raw)
        if header:
            current = int(header.group(1))
            continue
        if current is None or raw.startswith("-") or raw.startswith("\\"):
            continue
        if current == line:
            return " ".join(raw[1:].split())
        current += 1
    return None
