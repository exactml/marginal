"""`review.self_reflect`: a second look that re-scores or drops fresh findings."""

from __future__ import annotations

import asyncio
import sys

from pydantic import BaseModel, ConfigDict, Field

from marginal.cli.review import _estimate_tokens
from marginal.config.schema import ModelSpec
from marginal.providers.errors import ProviderError, ProviderResponseError
from marginal.providers.factory import get_provider
from marginal.review import Finding

CRITIQUE_INSTRUCTIONS = (
    "You are double-checking review findings generated for the pull request diff "
    "below, before any of them is posted. A false positive wastes the author's "
    "time, so check each finding against what the diff actually shows:\n"
    "- A diff shows only changed lines and a few lines of context; code between "
    "hunks and the rest of each file are not shown. A claim that rests on code the "
    "diff doesn't show (that something is unused, missing, never called, or "
    "handled nowhere) is unverified -- lower its confidence.\n"
    "- Is the problem in the file and at the line the finding names? Each file's "
    "diff is under its own `--- path ---` header.\n"
    "- If the code or a comment in the diff says the behavior is intentional, it's "
    "a trade-off, not a defect -- drop it unless it is clearly unsafe.\n"
    "- If it restates an earlier finding in this list, drop it.\n"
    "You can only lower a finding's confidence or drop it, never raise it. For "
    "each finding id, answer drop=true to remove it, or drop=false with its revised "
    "confidence between 0.0 and its current confidence that it's a real, "
    "actionable issue. Give a one-sentence reason either way."
)


class _Critique(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    drop: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class _CritiqueResponse(BaseModel):
    """Structured-output wrapper: one verdict per critiqued finding."""

    model_config = ConfigDict(extra="forbid")

    results: list[_Critique]


def critique_findings(
    model_spec: ModelSpec,
    findings: list[Finding],
    files: list[dict[str, object]],
    *,
    max_prompt_tokens: int,
) -> list[Finding]:
    """`findings` after one more model call lowers the confidence of, or drops,
    each of them.

    A revised confidence is capped at the first-pass one, so the critique can
    only keep a finding out, never push one over `confidence_threshold`.
    `files` must already be `_redact_patches` output. A finding the model
    doesn't answer is kept unchanged; answers for unknown ids are ignored.
    Best-effort: over `max_prompt_tokens`, or on any `ProviderError`, it logs
    one stderr line and returns `findings` unchanged -- they were already
    generated and paid for, so a failed optional pass mustn't lose them or
    fail the review.
    """
    prompt = _build_critique_prompt(findings, files)
    estimated_tokens = _estimate_tokens(prompt)
    if estimated_tokens > max_prompt_tokens:
        print(
            f"marginal review: skipped self-critique: the prompt is an estimated "
            f"{estimated_tokens:,} tokens, over review.max_prompt_tokens "
            f"({max_prompt_tokens:,}), so findings keep their first-pass confidence",
            file=sys.stderr,
        )
        return findings
    try:
        results = asyncio.run(_critique(model_spec, prompt))
    except ProviderError as exc:
        print(
            f"marginal review: self-critique failed, keeping findings as-is: {exc}", file=sys.stderr
        )
        return findings

    answers = {r.id: r for r in results}
    kept = []
    for n, finding in enumerate(findings, start=1):
        answer = answers.get(n)
        if answer is None:
            kept.append(finding)
        elif not answer.drop:
            kept.append(
                finding.model_copy(
                    update={"confidence": min(answer.confidence, finding.confidence)}
                )
            )
    print(
        f"marginal review: self-critique dropped {len(findings) - len(kept)} of "
        f"{len(findings)} finding(s)",
        file=sys.stderr,
    )
    return kept


def _build_critique_prompt(findings: list[Finding], files: list[dict[str, object]]) -> str:
    """The instructions, each finding with its id, then the diff the reviewer saw."""
    blocks = [
        f"--- finding {n} at {f.file if f.line is None else f'{f.file}:{f.line}'} · "
        f"{f.severity.value} · {f.confidence:.0%} confidence ---\n{f.message}"
        for n, f in enumerate(findings, start=1)
    ]
    diffs = [f"--- {file['filename']} ---\n{file['patch']}" for file in files]
    return "\n\n".join([CRITIQUE_INSTRUCTIONS, *blocks, "Diff:", *diffs])


async def _critique(model_spec: ModelSpec, prompt: str) -> list[_Critique]:
    provider = get_provider(model_spec)
    result = await provider.generate_structured(prompt, schema=_CritiqueResponse)
    if not isinstance(result, _CritiqueResponse):
        raise ProviderResponseError(
            f"expected a _CritiqueResponse from generate_structured, got {type(result).__name__}"
        )
    return result.results
