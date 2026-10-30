"""Out-of-diff callers of the definitions a pull request changes."""

from __future__ import annotations

import sys

from marginal.graph import ChangedDefinition, build_symbol_graph, find_out_of_diff_callers


def build_graph_context(
    repo_root: str, files: list[dict[str, object]], *, enabled: bool
) -> list[ChangedDefinition]:
    """The PR's changed definitions and their out-of-diff callers, or `[]`.

    `[]` both when `enabled` is `False` and when building the graph fails for
    any reason (`repo_root` isn't a git working tree, `git` isn't installed,
    a tracked file has invalid syntax) -- this context is a best-effort
    addition to the prompt, never something that should fail the review
    itself, the same way a missing policy file only warns rather than
    aborting.
    """
    if not enabled:
        return []
    try:
        graph = build_symbol_graph(repo_root)
        if graph.unparsed_files:
            shown = ", ".join(graph.unparsed_files[:3])
            more = len(graph.unparsed_files) - 3
            print(
                f"marginal review: warning: code graph skipped {len(graph.unparsed_files)} "
                f"file(s) it couldn't parse: {shown}" + (f" (+{more} more)" if more > 0 else ""),
                file=sys.stderr,
            )
        return find_out_of_diff_callers(graph, files)
    except Exception as exc:
        print(
            f"marginal review: warning: couldn't build code-graph context, skipping: {exc}",
            file=sys.stderr,
        )
        return []
