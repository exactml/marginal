"""Check what a finding claims, and decide whether it's posted -- no model call.

The model gives each finding a trigger and quotes the lines it rests on.
marginal verifies those quotes against the code and posts a finding only if
the evidence holds: at least one quote found at its line, and a trigger that
names real code. Every finding gets a plain reason for the decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from marginal.graph.diff import _hunk_ranges
from marginal.review import Checks, Finding, Severity

# A model often gets a quoted line's number slightly wrong; text that isn't
# there at all still fails.
QUOTE_LINE_TOLERANCE = 2
# Only the first quotes count; the prompt asks for 1-3.
MAX_QUOTES = 3
# A partial quote must be at least this long, without spaces, to match a line
# it's part of -- shorter ones (`return x`) match too many lines to prove anything.
_MIN_PARTIAL_QUOTE = 8

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)")
_WORD = re.compile(r"[A-Za-z_]\w*")
_BACKTICKED = re.compile(r"`([^`]+)`")
_CODE_LIKE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\(?")
# Too common to show that a trigger names this code rather than any code.
_NOT_A_NAME = {"self", "cls", "None", "True", "False", "return", "def", "class", "and", "not"}
_SEVERITY_RANK = {severity: rank for rank, severity in enumerate(Severity)}


@dataclass(frozen=True)
class Decision:
    """Whether a checked finding is posted, and why, in one phrase."""

    finding: Finding
    posted: bool
    reason: str


class CodeView:
    """The code marginal checks a finding against: the lines the diff shows
    (with the diff's own numbering), the rest of each file from the checkout,
    and the names in the diff and the caller context the model was given."""

    def __init__(self, repo_root: str, files: list[dict[str, object]], context: str = "") -> None:
        self._root = Path(repo_root).resolve()
        self._diff_lines: dict[str, dict[int, str]] = {}
        self._hunks: dict[str, list[tuple[int, int]]] = {}
        self._file_lines: dict[str, list[str] | None] = {}
        texts = [context]
        for file in files:
            name, patch = str(file["filename"]), str(file.get("patch") or "")
            self._diff_lines[name] = _new_lines(patch)
            self._hunks[name] = _hunk_ranges(patch)
            texts.append(patch)
        self._names = set(_WORD.findall("\n".join(texts)))

    def has_quote(self, file: str, line: int, quote: str) -> bool:
        """Whether `quote` is the line at `file:line`, give or take
        `QUOTE_LINE_TOLERANCE` lines, ignoring surrounding whitespace."""
        wanted = _normalize(_first_line(quote))
        if not wanted:
            return False
        for number in range(line - QUOTE_LINE_TOLERANCE, line + QUOTE_LINE_TOLERANCE + 1):
            text = self._line(file, number)
            if text is not None and _quote_matches(wanted, _normalize(text)):
                return True
        return False

    def in_diff(self, file: str, line: int) -> bool:
        return any(start <= line <= end for start, end in self._hunks.get(file, []))

    def names_code(self, trigger: str, quoted: list[str]) -> bool:
        """Whether `trigger` names at least one identifier -- a function,
        method, attribute or variable -- from the diff, the caller context,
        or the `quoted` lines already verified to be in the code."""
        known = self._names.union(*(_WORD.findall(q) for q in quoted))
        return bool(_code_names(trigger) & known)

    def _line(self, file: str, number: int) -> str | None:
        if number < 1:
            return None
        diff_line = self._diff_lines.get(file, {}).get(number)
        if diff_line is not None:
            return diff_line
        lines = self._read(file)
        return lines[number - 1] if lines is not None and number <= len(lines) else None

    def _read(self, file: str) -> list[str] | None:
        if file not in self._file_lines:
            path = (self._root / file).resolve()
            # The path comes from the model: never read outside the checkout.
            if not path.is_relative_to(self._root) or not path.is_file():
                self._file_lines[file] = None
            else:
                try:
                    self._file_lines[file] = path.read_text(errors="replace").splitlines()
                except OSError:
                    self._file_lines[file] = None
        return self._file_lines[file]


def check(finding: Finding, view: CodeView) -> Checks:
    """Verify `finding`'s quotes and trigger against `view`."""
    evidence = finding.evidence[:MAX_QUOTES]
    quotes = tuple(view.has_quote(e.file, e.line, e.quote) for e in evidence)
    verified = [e for e, ok in zip(evidence, quotes, strict=True) if ok]
    return Checks(
        quotes=quotes,
        trigger_concrete=view.names_code(finding.trigger, [e.quote for e in verified]),
        caller_shown=any(not view.in_diff(e.file, e.line) for e in verified),
    )


def decide(findings: list[Finding], view: CodeView, *, max_comments: int) -> list[Decision]:
    """Check every finding and apply the rule: post a finding that has at
    least one verified quote and a concrete trigger.

    Posted findings come first, most severe first, then the one with more
    verified quotes; past `max_comments` the rest are dropped too. Each
    finding's checks are attached to it (`Finding.checks`).
    """
    passing, decisions = [], []
    for finding in findings:
        finding._checks = check(finding, view)
        failure = _failure(finding._checks)
        if failure is None:
            passing.append(finding)
        else:
            decisions.append(Decision(finding, posted=False, reason=failure))
    passing.sort(key=lambda f: (-_SEVERITY_RANK[f.severity], -f._checks.quotes_verified))
    posted = [Decision(f, posted=True, reason=_posted_reason(f._checks)) for f in passing]
    for decision in posted[max_comments:]:
        decisions.append(
            Decision(decision.finding, posted=False, reason="over review.max_comments")
        )
    return posted[:max_comments] + decisions


def _failure(checks: Checks) -> str | None:
    if not checks.quotes:
        return "no quoted evidence"
    if not checks.quotes_verified:
        return "quoted line not found"
    if not checks.trigger_concrete:
        return "no concrete trigger"
    return None


def _posted_reason(checks: Checks) -> str:
    n = checks.quotes_verified
    reason = f"{n} verified quote{'s' * (n != 1)}, concrete trigger"
    return reason + (", caller shown" if checks.caller_shown else "")


def _new_lines(patch: str) -> dict[int, str]:
    """Each line of the new file the patch shows, by its new line number."""
    lines, number = {}, None
    for row in patch.splitlines():
        header = _HUNK_HEADER.match(row)
        if header:
            number = int(header.group(1))
        elif number is not None and row[:1] in (" ", "+"):
            lines[number] = row[1:]
            number += 1
    return lines


def _first_line(quote: str) -> str:
    return next((line for line in quote.splitlines() if line.strip()), "")


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _quote_matches(quote: str, line: str) -> bool:
    if quote == line:
        return True
    return len(quote.replace(" ", "")) >= _MIN_PARTIAL_QUOTE and quote in line


def _code_names(text: str) -> set[str]:
    """Names in `text` that look like code: anything in backticks, and words
    with an underscore, a dot, a call's `(`, or an inner capital."""
    names: set[str] = set()
    for span in _BACKTICKED.findall(text):
        names.update(_WORD.findall(span))
    for match in _CODE_LIKE.finditer(text):
        word = match.group()
        bare = word.rstrip("(")
        if word.endswith("(") or "_" in bare or "." in bare or re.search(r"[a-z][A-Z]", bare):
            names.update(_WORD.findall(bare))
    return {name for name in names if len(name) >= 3 and name not in _NOT_A_NAME}
