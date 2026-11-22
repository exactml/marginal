"""Knowledge proposals read from a pull request's diff (ADR 0011), with no model call.

A merged pull request proposes candidate claims. None of them is knowledge yet:
the team decides which go into the graph in a separate review step.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from marginal.oic.domain.schema import Relation

PROPOSAL_MARKER = "<!-- marginal:proposal -->"
PROPOSAL_HEADING = "### 📚 marginal knowledge proposal"

PullRequestState = Literal["open", "merged", "closed"]

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)")
_ANY_HUNK_HEADER = re.compile(r"^@@ -(\S+) \+(\S+) @@(.*)$")
_REQUIREMENT = re.compile(r"([A-Za-z][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*(.*)")
# A TOML basic ("...") or literal ('...') string.
_QUOTED = re.compile(r"""(["'])(.+?)\1""")
_TOML_STRING = re.compile(r"""^(name|version)\s*=\s*(["'])(.+?)\2$""")
_TOML_TABLE = re.compile(r"^\[\[?([^\]]+)\]\]?$")
_TOML_ARRAY = re.compile(r"^([\w.-]+)\s*=\s*\[(.*)$")
_REQUIREMENTS_FILE = re.compile(r"requirements[\w.-]*\.txt")
# A reply to a finding with one of these explains a choice, not a fix. Not
# "because" or "expected": fix replies use them too ("fixed, because ...").
_DECISION_WORDS = re.compile(
    r"\b(intentional(ly)?|by design|on purpose|deliberate(ly)?|as intended|not a bug|"
    r"we want|we chose|we decided)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


@dataclass(frozen=True)
class ProposedClaim:
    subject: str
    relation: Relation
    object: str
    source: str = ""
    # Why, when the evidence says so (a dependency line's comment); not part of the id.
    reason: str = ""

    @property
    def id(self) -> str:
        """Same subject, relation and object give the same id, so the review
        step can refer to a claim and spot one proposed again."""
        key = f"{self.subject}|{self.relation.value}|{self.object}"
        return hashlib.sha256(key.encode()).hexdigest()[:6]


def extract_claims(
    repo: str,
    files: Iterable[dict[str, object]],
    head_contents: dict[str, str] | None = None,
    base_contents: dict[str, str] | None = None,
) -> list[ProposedClaim]:
    """The new claims `files` (GitHub's PR files, with patches) evidence, in
    diff order, each once. Which files a PR touched is not a claim: git
    already has it.

    `head_contents` and `base_contents` map a path to its full text at the
    PR's head and base, for files whose patch alone can't say what a line
    means (`pyproject.toml`)."""
    claims: list[ProposedClaim] = []
    for file in files:
        path = str(file["filename"])
        patch = str(file.get("patch") or "")
        new = _claims(repo, path, patch, (head_contents or {}).get(path))
        # An edited line shows as removed + added; what it already said isn't new.
        old = _claims(repo, path, _reverse(patch), (base_contents or {}).get(path))
        known = {claim.id for claim in old}
        claims.extend(claim for claim in new if claim.id not in known)
    return list({claim.id: claim for claim in claims}.values())


def _claims(repo: str, path: str, patch: str, text: str | None) -> list[ProposedClaim]:
    """Claims from the lines `patch` adds to `path`."""
    name = PurePosixPath(path).name
    if name == "CODEOWNERS":
        return list(_owners(path, patch))
    if _REQUIREMENTS_FILE.fullmatch(name):
        return list(_requirements_txt(repo, path, patch))
    if name == "pyproject.toml":
        return list(_pyproject(repo, path, patch, text))
    return []


def _reverse(patch: str) -> str:
    """`patch` undone: its removed lines become added ones, with old-file numbers."""
    rows = []
    for row in patch.splitlines():
        header = _ANY_HUNK_HEADER.match(row)
        if header:
            rows.append(f"@@ -{header.group(2)} +{header.group(1)} @@{header.group(3)}")
        elif row[:1] in ("+", "-"):
            rows.append({"+": "-", "-": "+"}[row[:1]] + row[1:])
        else:
            rows.append(row)
    return "\n".join(rows)


def render_proposal(claims: list[ProposedClaim], state: PullRequestState) -> str:
    """The proposal comment for a PR in `state`."""
    lines = [PROPOSAL_MARKER, PROPOSAL_HEADING, ""]
    if state == "closed":
        lines.append("Closed without merging, so nothing is proposed.")
        return "\n".join(lines)
    if not claims:
        lines.append("No knowledge found in this PR.")
        return "\n".join(lines)
    intro = (
        "Merged. Proposed for the knowledge graph:"
        if state == "merged"
        else "When merged, this PR will propose:"
    )
    lines += [
        intro,
        "",
        "| id | subject | relation | object | why | source |",
        "|---|---|---|---|---|---|",
    ]
    for claim in claims:
        cells = [_code(claim.id), _code(claim.subject), claim.relation.value, _code(claim.object)]
        # A code span, like the other cells: `@team` in a comment mustn't ping anyone.
        cells.append(_code(claim.reason) if claim.reason else "")
        cells.append(_code(claim.source) if claim.source else "")
        lines.append(f"| {' | '.join(cells)} |")
    lines += [
        "",
        "These are candidates, not knowledge yet: the team reviews them before "
        "any goes into the graph.",
    ]
    return "\n".join(lines)


def decisions_from_replies(
    replies: Iterable[tuple[str, int | None, str]],
) -> list[ProposedClaim]:
    """A decision for each `(path, line, reply)` that answers a review finding
    by explaining a choice ("intentional: zero-stock items stay listed"),
    about the file the finding was on."""
    claims = []
    for path, line, reply in replies:
        text = " ".join(reply.split())
        if not _DECISION_WORDS.search(text):
            continue
        # The first sentence carries the decision; the rest is usually detail.
        sentence = _SENTENCE_END.split(text, 1)[0][:200]
        source = f"{path}:{line}" if line else path
        claims.append(ProposedClaim(f"decision: {sentence}", Relation.DECISION_ABOUT, path, source))
    return list({claim.id: claim for claim in claims}.values())


def knowledge_claims(
    knowledge: Iterable[tuple[str, str, str, str, int, str]],
    files: Iterable[dict[str, object]],
) -> list[ProposedClaim]:
    """A claim for each `(kind, statement, about, file, line, quote)` a review
    reported whose quote is still on a line of `file` in the merged diff: a
    later push may have removed what the rule or decision rested on.

    The claim is about a path in the PR, so a reviewer can look it up by the
    files a later PR changes: `about` when it names one, else `file`."""
    shown = {
        str(file["filename"]): [
            " ".join(text.split()) for _, text, _ in _patch_lines(str(file.get("patch") or ""))
        ]
        for file in files
    }
    relation = {"rule": Relation.CONSTRAINS, "decision": Relation.DECISION_ABOUT}
    claims = []
    for kind, statement, about, file, line, quote in knowledge:
        quote = " ".join(quote.split())
        still_there = bool(quote) and any(quote in text for text in shown.get(file, []))
        if kind in relation and still_there:
            path = about if about in shown else file
            claims.append(
                ProposedClaim(f"{kind}: {statement}", relation[kind], path, f"{file}:{line}")
            )
    return list({claim.id: claim for claim in claims}.values())


def _code(value: str) -> str:
    """`value` as a code span that can't end early or split a table cell."""
    return "`" + value.replace("`", "'").replace("|", "\\|") + "`"


def _patch_lines(patch: str) -> Iterator[tuple[int, str, bool]]:
    """`(new line number, text, added)` for each line of the new file the patch shows."""
    number = None
    for row in patch.splitlines():
        header = _HUNK_HEADER.match(row)
        if header:
            number = int(header.group(1))
        elif number is not None and row[:1] in (" ", "+"):
            yield number, row[1:], row[:1] == "+"
            number += 1


def _owners(path: str, patch: str) -> Iterator[ProposedClaim]:
    for number, text, added in _patch_lines(patch):
        parts = text.split("#", 1)[0].split()
        if added and len(parts) > 1:
            for owner in parts[1:]:
                yield ProposedClaim(parts[0], Relation.OWNED_BY, owner, f"{path}:{number}")


def _requirements_txt(repo: str, path: str, patch: str) -> Iterator[ProposedClaim]:
    for number, text, added in _patch_lines(patch):
        spec, comment = _split_comment(text)
        spec = spec.strip()
        if added and spec and not spec.startswith("-"):
            yield from _dependency(repo, spec, f"{path}:{number}", comment.strip())


def _pyproject(
    repo: str, path: str, patch: str, text: str | None = None
) -> Iterator[ProposedClaim]:
    """Release and dependency claims from the patch's added lines. With the
    file's full `text`, each line's table and array come from the whole file;
    without it, only from what the patch shows, so a table header above a hunk
    is missed and the repo name stands in for the project's."""
    added = {number for number, _, is_added in _patch_lines(patch) if is_added}
    rows = (
        enumerate(text.splitlines(), 1)
        if text is not None
        else ((number, line) for number, line, _ in _patch_lines(patch))
    )
    project, table, array = repo, "", None
    for number, raw in rows:
        line, comment = _split_comment(raw)
        line = line.strip()
        header = _TOML_TABLE.match(line)
        if header:
            table, array = header.group(1).strip(), None
            continue
        field = _TOML_STRING.match(line)
        if field and table in ("", "project"):  # "": the table header isn't in the hunk
            if field.group(1) == "name":
                project = field.group(3)
            elif number in added:
                version = field.group(3)
                yield ProposedClaim(
                    f"{project}@{version}", Relation.RELEASE_OF, project, f"{path}:{number}"
                )
            continue
        opened = _TOML_ARRAY.match(line)
        if opened:
            array, line = opened.group(1), opened.group(2)
        if number in added and array and _is_dependency_array(table, array):
            for _, spec in _QUOTED.findall(line):
                yield from _dependency(project, spec, f"{path}:{number}", comment.strip())
        if line.rstrip(", ").endswith("]"):  # not `]` alone: extras like `pkg[x]` have one
            array = None


def _is_dependency_array(table: str, array: str) -> bool:
    if table in ("project.optional-dependencies", "dependency-groups"):
        return True
    return array == "dependencies" and table in ("", "project")


def _split_comment(line: str) -> tuple[str, str]:
    """`line` and its trailing `#` comment; a `#` inside quotes isn't one."""
    quote = None
    for i, char in enumerate(line):
        if char in "\"'" and quote in (None, char):
            quote = None if quote else char
        elif char == "#" and not quote:
            return line[:i], line[i + 1 :].strip()
    return line, ""


def _dependency(repo: str, spec: str, source: str, reason: str = "") -> Iterator[ProposedClaim]:
    """`installs name@version` for an exact pin, else `dependsOn` with the range
    in the object, so a raised floor (`>=3.0.0` to `>=3.0.4`) is a new claim."""
    spec = spec.split(";", 1)[0].strip()
    if "://" in spec:
        # `name @ url` names its package; a bare URL or VCS line names none.
        named = _REQUIREMENT.fullmatch(spec.split("@", 1)[0].strip()) if "@" in spec else None
        if named:  # the name without extras, as for any other dependency
            yield ProposedClaim(repo, Relation.DEPENDS_ON, named.group(1).lower(), source, reason)
        return
    match = _REQUIREMENT.fullmatch(spec)
    if not match:
        return
    name, constraint = match.group(1).lower(), "".join(match.group(2).split())
    if constraint.startswith("==") and "*" not in constraint and "," not in constraint:
        yield ProposedClaim(repo, Relation.INSTALLS, f"{name}@{constraint[2:]}", source, reason)
    else:
        yield ProposedClaim(repo, Relation.DEPENDS_ON, f"{name}{constraint}", source, reason)
