"""Knowledge proposals read from a pull request's diff (ADR 0011), with no model call.

A pull request proposes claims; merging accepts the ones no writer dropped.
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
_DROP = re.compile(r"^\s*/marginal drop\s+([0-9a-f][0-9a-f ,]*)\s*$", re.MULTILINE)
_REQUIREMENT = re.compile(r"([A-Za-z][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*(.*)")
_QUOTED = re.compile(r'"([^"]+)"')
_TOML_STRING = re.compile(r'^(name|version)\s*=\s*"([^"]+)"$')
_TOML_TABLE = re.compile(r"^\[\[?([^\]]+)\]\]?$")
_TOML_ARRAY = re.compile(r"^([\w.-]+)\s*=\s*\[(.*)$")
_REQUIREMENTS_FILE = re.compile(r"requirements[\w.-]*\.txt")


@dataclass(frozen=True)
class ProposedClaim:
    subject: str
    relation: Relation
    object: str
    source: str = ""

    @property
    def id(self) -> str:
        """Same subject, relation and object give the same id on every push,
        so a drop keeps applying to the claim."""
        key = f"{self.subject}|{self.relation.value}|{self.object}"
        return hashlib.sha256(key.encode()).hexdigest()[:6]


def extract_claims(
    repo: str,
    pr_number: int,
    files: Iterable[dict[str, object]],
    contents: dict[str, str] | None = None,
) -> list[ProposedClaim]:
    """The claims `files` (GitHub's PR files, with patches) evidence, in diff order,
    each once. `contents` maps a path to its full text at the PR's head, for
    files whose patch alone can't say what a line means (`pyproject.toml`)."""
    claims: list[ProposedClaim] = []
    for file in files:
        path = str(file["filename"])
        patch = str(file.get("patch") or "")
        directory = str(PurePosixPath(path).parent)
        claims.append(
            ProposedClaim(
                f"PR #{pr_number}",
                Relation.CHANGES,
                repo if directory == "." else directory,
                path,
            )
        )
        name = PurePosixPath(path).name
        if name == "CODEOWNERS":
            claims.extend(_owners(path, patch))
        elif _REQUIREMENTS_FILE.fullmatch(name):
            claims.extend(_requirements_txt(repo, path, patch))
        elif name == "pyproject.toml":
            claims.extend(_pyproject(repo, path, patch, (contents or {}).get(path)))
    return list({claim.id: claim for claim in claims}.values())


def requested_drops(comments: Iterable[dict[str, object]]) -> list[tuple[str, set[str]]]:
    """`(login, claim ids)` for each `/marginal drop <id> ...` comment, oldest
    first. Who may drop is the caller's check."""
    drops = []
    for comment in comments:
        body = str(comment.get("body") or "")
        if PROPOSAL_MARKER in body:
            continue
        ids = {i for match in _DROP.findall(body) for i in re.split(r"[ ,]+", match) if i}
        login = str((comment.get("user") or {}).get("login", ""))
        if ids and login:
            drops.append((login, ids))
    return drops


def render_proposal(
    claims: list[ProposedClaim], dropped: dict[str, str], state: PullRequestState
) -> str:
    """The proposal comment for a PR in `state`; `dropped` maps claim id to who dropped it."""
    intro = {
        "open": "This PR would record:",
        "merged": "Merged. These claims are accepted:",
        "closed": "Closed without merging. These claims were not recorded:",
    }[state]
    lines = [PROPOSAL_MARKER, PROPOSAL_HEADING, ""]
    if not claims:
        lines.append("No relations found in this PR.")
        return "\n".join(lines)
    lines += [intro, "", "| id | subject | relation | object | source |", "|---|---|---|---|---|"]
    for claim in claims:
        cells = [_code(claim.id), _code(claim.subject), claim.relation.value, _code(claim.object)]
        if claim.id in dropped:
            # Backticked login: a bare @name would notify that person on every update.
            cells = [f"~~{cell}~~" for cell in cells] + [f"dropped by {_code(dropped[claim.id])}"]
        else:
            cells.append(_code(claim.source) if claim.source else "")
        lines.append(f"| {' | '.join(cells)} |")
    if state == "open":
        lines += [
            "",
            "Reply `/marginal drop <id>` to exclude a claim (needs write access). "
            "Merging accepts the rest.",
        ]
    return "\n".join(lines)


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
        spec = text.split("#", 1)[0].strip()
        if added and spec and not spec.startswith("-"):
            yield from _dependency(repo, spec, f"{path}:{number}")


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
        line = raw.split("#", 1)[0].strip()
        header = _TOML_TABLE.match(line)
        if header:
            table, array = header.group(1).strip(), None
            continue
        field = _TOML_STRING.match(line)
        if field and table in ("", "project"):  # "": the table header isn't in the hunk
            if field.group(1) == "name":
                project = field.group(2)
            elif number in added:
                version = field.group(2)
                yield ProposedClaim(
                    f"{project}@{version}", Relation.RELEASE_OF, project, f"{path}:{number}"
                )
            continue
        opened = _TOML_ARRAY.match(line)
        if opened:
            array, line = opened.group(1), opened.group(2)
        if number in added and array and _is_dependency_array(table, array):
            for spec in _QUOTED.findall(line):
                yield from _dependency(repo, spec, f"{path}:{number}")
        if line.rstrip(", ").endswith("]"):  # not `]` alone: extras like `pkg[x]` have one
            array = None


def _is_dependency_array(table: str, array: str) -> bool:
    if table in ("project.optional-dependencies", "dependency-groups"):
        return True
    return array == "dependencies" and table in ("", "project")


def _dependency(repo: str, spec: str, source: str) -> Iterator[ProposedClaim]:
    match = _REQUIREMENT.fullmatch(spec.split(";", 1)[0].strip())
    if not match:
        return
    name, constraint = match.group(1).lower(), match.group(2).strip()
    if constraint.startswith("==") and "*" not in constraint:
        yield ProposedClaim(repo, Relation.INSTALLS, f"{name}@{constraint[2:].strip()}", source)
    else:
        yield ProposedClaim(repo, Relation.DEPENDS_ON, name, source)
