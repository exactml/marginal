"""Map a diff's changed definitions to their out-of-diff callers."""

from __future__ import annotations

import re
from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field

from marginal.graph.symbols import CallSite, Definition, SymbolGraph

__all__ = ["ChangedDefinition", "find_out_of_diff_callers"]

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class ChangedDefinition(BaseModel):
    """A `Definition` whose line span overlaps one of a diff's hunks.

    `callers` only ever holds call sites outside the diff's own changed
    files -- a caller already visible in the diff gives a reviewer nothing
    the diff doesn't already show it directly, so it's dropped rather than
    repeated.
    """

    model_config = ConfigDict(extra="forbid")

    definition: Definition
    callers: list[CallSite] = Field(default_factory=list)


def find_out_of_diff_callers(
    graph: SymbolGraph, files: list[dict[str, object]]
) -> list[ChangedDefinition]:
    """Every `graph` definition a PR's diff touches, with its out-of-diff callers.

    `files` is the same GitHub "pull request files" shape `marginal.cli.review`
    already works with: each entry's `filename` and `patch` (a unified diff,
    absent or empty for a binary/oversized file GitHub didn't send one for --
    that file simply contributes no hunks, and so no changed definitions). A
    definition counts as touched if any hunk's new-file line range overlaps
    its `line_start`..`line_end` span; an unchanged definition is skipped
    entirely, and a definition touched by more than one hunk is only
    reported once.
    """
    changed_files = {str(file["filename"]) for file in files}
    definitions_by_file: dict[str, list[Definition]] = defaultdict(list)
    for definition in graph.definitions.values():
        definitions_by_file[definition.file].append(definition)

    changed: dict[str, ChangedDefinition] = {}
    for file in files:
        filename = str(file["filename"])
        patch = str(file.get("patch", ""))
        candidates = definitions_by_file.get(filename, [])
        for start, end in _hunk_ranges(patch):
            for definition in candidates:
                if definition.qualified_name in changed:
                    continue
                if definition.line_end < start or definition.line_start > end:
                    continue
                callers = [
                    site
                    for site in graph.callers.get(definition.qualified_name, [])
                    if site.file not in changed_files
                ]
                changed[definition.qualified_name] = ChangedDefinition(
                    definition=definition, callers=callers
                )

    return list(changed.values())


def _hunk_ranges(patch: str) -> list[tuple[int, int]]:
    """The new-file `(start, end)` inclusive line range of every hunk in `patch`."""
    ranges = []
    for line in patch.splitlines():
        match = _HUNK_HEADER.match(line)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        ranges.append((start, start + max(count, 1) - 1))
    return ranges
