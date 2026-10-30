"""The prompts marginal sends the reviewer model.

Instruction text lives in `prompts/*.md`, shipped as package data; the
builders here fold the diff and its context in around it.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from importlib import resources
from pathlib import Path, PurePosixPath

from marginal.graph import CallSite, ChangedDefinition
from marginal.review.redact import redact_secrets
from marginal.review.replies import ReplyThread
from marginal.review.schema import MAX_FINDINGS_PER_REVIEW

# Total out-of-diff caller snippets folded into the prompt across every
# changed definition -- bounds the prompt against a definition with a huge
# fan-out, independent of repo size.
MAX_GRAPH_CONTEXT_CALLERS = 10

# Lines of source shown above and below a caller's own line.
_GRAPH_CONTEXT_SNIPPET_RADIUS = 2

# Most-recent maintainer-answered threads folded into the prompt, and the
# characters kept from each thread's comment and from its replies -- bounds
# the prompt on a PR with a long back-and-forth.
MAX_REPLY_THREADS = 10
_REPLY_COMMENT_CHARS = 600
_REPLY_TEXT_CHARS = 1500

# Rough characters-per-token ratio for estimating a prompt's size without a
# provider-specific tokenizer. Code and diffs tokenize denser than English
# prose (~4 chars/token), so 3 errs toward over-counting: the cap stays a
# real ceiling rather than one a prompt can quietly overshoot.
_CHARS_PER_TOKEN = 3


def load_prompt(name: str) -> str:
    """The text of `prompts/<name>.md`, read from the installed package."""
    text = (resources.files("marginal.review") / "prompts" / f"{name}.md").read_text("utf-8")
    return text.removesuffix("\n")


FINDING_PROMPT_INSTRUCTIONS = load_prompt("finding").format(max_findings=MAX_FINDINGS_PER_REVIEW)

RECHECK_INSTRUCTIONS = load_prompt("recheck")


class PromptOverBudget(Exception):
    """The built prompt's estimated size exceeds `review.max_prompt_tokens`."""


def estimate_tokens(text: str) -> int:
    """Rough token count for `text`. Exact counts are provider- and
    model-specific; this only needs to catch prompts far beyond normal size."""
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


def build_finding_prompt(
    files: list[dict[str, object]],
    policies: list[tuple[str, str]],
    graph_context: list[ChangedDefinition],
    repo_root: str,
    replies: list[ReplyThread] | None = None,
    anti_policies: list[tuple[str, str]] | None = None,
    ci_conclusion: str | None = None,
) -> str:
    """The reviewer prompt. `files` must already be `redact_patches` output."""
    diff = "\n\n".join(f"--- {file['filename']} ---\n{file['patch']}" for file in files)
    sections = [FINDING_PROMPT_INSTRUCTIONS]
    if policies:
        policy_text = "\n\n".join(f"--- {path} ---\n{content}" for path, content in policies)
        sections.append(
            "Also weigh the diff against this repository's own engineering policies "
            "below -- a violation of one of these is at least as important as a "
            f"general code-quality issue:\n\n{policy_text}"
        )
    if anti_policies:
        anti_policy_text = "\n\n".join(
            f"--- {path} ---\n{content}" for path, content in anti_policies
        )
        sections.append(
            "Never flag anything that this repository's anti-policies below describe "
            "-- each is a deliberate, accepted decision the maintainers don't want "
            "raised in review. Leave such issues out of your findings entirely, even "
            f"if they would otherwise look like a problem:\n\n{anti_policy_text}"
        )
    if ci_conclusion:
        sections.append(
            f"CI status: {ci_conclusion} (the GitHub Actions run that triggered this "
            "review). Weigh it as context only: a failing run is not itself a finding, "
            "and a passing one doesn't clear the diff -- flag only what the diff shows."
        )
    graph_section = build_graph_context_section(graph_context, repo_root)
    if graph_section:
        sections.append(graph_section)
    if replies:
        sections.append(build_replies_section(replies))
    sections.append(diff)
    return "\n\n".join(sections)


def build_graph_context_section(
    graph_context: list[ChangedDefinition], repo_root: str
) -> str | None:
    """A prompt section naming out-of-diff callers of what this diff changes.

    `None` if there's nothing to show -- `graph_context` is empty, every
    changed definition's callers are all inside the diff already, or none of
    the caller files could be read for a snippet. Bounded to
    `MAX_GRAPH_CONTEXT_CALLERS` caller snippets total, across every changed
    definition, so a definition with a huge fan-out can't blow up the prompt.
    """
    # Share the budget round-robin, one caller per definition per pass, so each
    # changed definition gets callers before any gets many: library code before
    # tests, then a changed method before the class around it, whose many
    # callers would otherwise fill the budget.
    ordered = sorted(
        graph_context,
        key=lambda c: (
            is_test_path(c.definition.file),
            c.definition.line_end - c.definition.line_start,
        ),
    )
    pending: list[Iterator[CallSite] | None] = [iter(c.callers) for c in ordered]
    picked: list[list[str]] = [[] for _ in ordered]
    remaining = MAX_GRAPH_CONTEXT_CALLERS
    while remaining > 0 and any(sites is not None for sites in pending):
        for i, sites in enumerate(pending):
            if sites is None or remaining <= 0:
                continue
            for site in sites:
                snippet = _read_snippet(repo_root, site.file, site.line)
                if snippet is not None:
                    picked[i].append(f"{site.file}:{site.line}\n{snippet}")
                    remaining -= 1
                    break
            else:
                pending[i] = None
    blocks = [
        f"`{changed.definition.qualified_name}` (defined in "
        f"{changed.definition.file}) is called from:\n\n" + "\n\n".join(picked[i])
        for i, changed in enumerate(ordered)
        if picked[i]
    ]
    if not blocks:
        return None
    return (
        "This diff changes definitions that other, unchanged files in the repo call -- "
        "check whether the change is compatible with how they're used there:\n\n"
        + "\n\n".join(blocks)
    )


def is_test_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    name = parts[-1] if parts else ""
    return (
        bool({"tests", "test"} & set(parts))
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def build_replies_section(replies: list[ReplyThread]) -> str:
    """A prompt section quoting maintainer answers to marginal's earlier comments.

    Keeps the `MAX_REPLY_THREADS` most recent threads, clips each comment and
    its replies, and runs the result through `redact_secrets` -- the text is
    human-written, but may still quote code from the diff.
    """
    blocks = []
    for thread in replies[-MAX_REPLY_THREADS:]:
        location = thread.path if thread.line is None else f"{thread.path}:{thread.line}"
        reply_text = "\n\n".join(thread.replies)
        blocks.append(
            f"--- {location} ---\n"
            f"marginal's earlier comment:\n{_clip(thread.comment, _REPLY_COMMENT_CHARS)}\n\n"
            f"Maintainer reply:\n{_clip(reply_text, _REPLY_TEXT_CHARS)}"
        )
    return redact_secrets(
        "A maintainer already answered some of marginal's earlier comments on this pull "
        "request. Don't raise any of these points again -- reworded, or on a nearby line -- "
        "unless the code it's about has changed in a way the reply doesn't cover:\n\n"
        + "\n\n".join(blocks)
    )


def _clip(text: str, limit: int) -> str:
    """`text`, cut to `limit` characters with a ` [...]` mark if it was longer."""
    return text if len(text) <= limit else text[:limit].rstrip() + " [...]"


def _read_snippet(repo_root: str, file: str, line: int) -> str | None:
    """A few lines of `file` around `line` (1-indexed), secrets redacted, or
    `None` if unreadable. The file is outside the diff, so nothing else
    redacts it before it reaches the model."""
    try:
        lines = Path(repo_root, file).read_text().splitlines()
    except OSError:
        return None
    start = max(line - _GRAPH_CONTEXT_SNIPPET_RADIUS, 1)
    end = min(line + _GRAPH_CONTEXT_SNIPPET_RADIUS, len(lines))
    return redact_secrets("\n".join(f"{n}: {lines[n - 1]}" for n in range(start, end + 1)))
