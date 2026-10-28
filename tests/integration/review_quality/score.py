"""Score review-quality benchmark runs against the answer key in cases.yml.

Reads `raw/<attempt id>/<case-id>/<run>.json` -- one `marginal review
--format json` output each, plus the wall-clock `seconds` run.py adds --
writes score.json with one score per attempt, and prints a Markdown
comparison with baseline.json for the CI run summary.
A regression only gets a warning: the exit code is non-zero for broken input
alone, never for a worse score.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from marginal.providers.pricing import price_for
from marginal.review import Severity

HERE = Path(__file__).parent

_SEVERITY_RANK = {severity.value: rank for rank, severity in enumerate(Severity)}

# (key, label, how it's formatted and when a change counts as a regression)
_METRICS = [
    ("recall", "Recall", "ratio"),
    ("recall_before_rules", "Recall before rules", "ratio"),
    ("precision", "Precision", "ratio"),
    ("accuracy", "Accuracy (per PR)", "ratio"),
    ("severity_accuracy", "Severity accuracy", "ratio"),
    ("evidence_accuracy", "Evidence accuracy", "ratio"),
    ("seconds", "Time", "seconds"),
    ("cost_usd", "Cost", "usd"),
    ("duplicates", "Duplicate findings", "count"),
    ("unlabeled", "Unlabeled findings", "count"),
]
# One plain sentence per metric, shown next to it in the run summary.
_MEANING = {
    "recall": "Known bugs the reviewer posted a finding for",
    "recall_before_rules": "Known bugs the model raised, posted or dropped by the posting rules",
    "precision": "Posted findings that point at a known bug, not at clean code",
    "accuracy": "PRs judged right: a bug PR with a hit, a clean PR with no findings",
    "severity_accuracy": "Hits rated at or above the expected severity",
    "evidence_accuracy": "Hits whose verified quotes include the bug's own lines",
    "seconds": "Median seconds per review",
    "cost_usd": "Model cost in USD of reviewing every case once",
    "duplicates": "Extra findings on a bug already hit",
    "unlabeled": "Findings outside the answer key, for a person to judge",
}
# Time and cost swing more between runs than the ratios, so they warn only on
# a relative increase this large.
_SLOWER_TOLERANCE = 0.25
# What score.json keeps of an unlabeled finding.
_FINDING_KEYS = ("file", "line", "severity", "confidence", "message")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Location(_Strict):
    file: str
    lines: tuple[int, int]

    @field_validator("lines")
    @classmethod
    def _check_range(cls, lines: tuple[int, int]) -> tuple[int, int]:
        if not 1 <= lines[0] <= lines[1]:
            raise ValueError(f"lines must be [start, end] with 1 <= start <= end, got {lines}")
        return lines

    def contains(self, file: str, line: int | None, end_line: int | None = None) -> bool:
        """Whether a finding at `line` (through `end_line`, for a tool that
        flags a range) touches this location."""
        if line is None or file != self.file:
            return False
        return line <= self.lines[1] and (end_line or line) >= self.lines[0]


class Expected(Location):
    severity: Severity


class Case(_Strict):
    id: str = Field(min_length=1)
    upstream: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    base: str = Field(min_length=7)
    head: str = Field(min_length=7)
    kind: Literal["security", "dependency", "caller", "logic", "test", "clean"]
    # When the source PR merged, so scores can be split by a model's training cutoff.
    merged: date
    source: str
    evidence: str | None = None
    # One line naming the bug, so a person can check a reviewer's finding against it.
    why: str | None = None
    must_find: list[Expected] = Field(default_factory=list)
    must_not_flag: list[Location] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_answer_key(self) -> Case:
        if (self.kind == "clean") == bool(self.must_find):
            raise ValueError(
                f"{self.id}: a clean case has no must_find; every other kind needs one"
            )
        return self


class Attempt(_Strict):
    """One reviewer every case is reviewed with: a review tool, and the
    provider and model it calls."""

    tool: Literal["marginal", "pr-agent"]
    provider: Literal["anthropic", "openai", "ollama"]
    model: str = Field(min_length=1)

    @property
    def id(self) -> str:
        return f"{self.tool}/{self.provider}/{self.model}"


class Suite(_Strict):
    config: str
    attempts: list[Attempt] = Field(min_length=1)
    cases: list[Case]

    @model_validator(mode="after")
    def _check_unique_ids(self) -> Suite:
        for name, ids in (
            ("attempt", [attempt.id for attempt in self.attempts]),
            ("case", [case.id for case in self.cases]),
        ):
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {name} ids in {ids}")
        return self


def load_suite(path: Path) -> Suite:
    return Suite.model_validate(yaml.safe_load(path.read_text()))


def review_cost(usage: dict | None) -> float | None:
    """The review's cost in USD, or None when the model or a token count is
    unknown -- a missing price is never guessed."""
    usage = usage or {}
    price = price_for(usage.get("model") or "")
    tokens_in, tokens_out = usage.get("input_tokens"), usage.get("output_tokens")
    if price is None or tokens_in is None or tokens_out is None:
        return None
    return (tokens_in * price.input + tokens_out * price.output) / 1_000_000


def score_review(case: Case, review: dict) -> dict:
    """Match one review's findings against the case's answer key.

    Each must_find entry is hit at most once, by the first finding inside its
    range; later findings there are duplicates, not false positives.
    """
    hit_by: list[dict | None] = [None] * len(case.must_find)
    false_positives = duplicates = 0
    unlabeled = []
    for finding in review["findings"]:
        file, line, end = finding["file"], finding["line"], finding.get("end_line")
        matched = [i for i, entry in enumerate(case.must_find) if entry.contains(file, line, end)]
        if matched:
            free = [i for i in matched if hit_by[i] is None]
            if free:
                hit_by[free[0]] = finding
            else:
                duplicates += 1
        elif case.kind == "clean" or any(
            loc.contains(file, line, end) for loc in case.must_not_flag
        ):
            false_positives += 1
        else:
            unlabeled.append(finding)
    hits = [(f, entry) for f, entry in zip(hit_by, case.must_find, strict=True) if f is not None]
    # Also counting what the posting rules dropped tells a model that missed
    # the bug apart from a finding that couldn't back itself up.
    raised = review["findings"] + review.get("dropped_findings", [])
    return {
        "expected": len(case.must_find),
        "hits": len(hits),
        "hits_before_rules": sum(
            any(entry.contains(f["file"], f["line"], f.get("end_line")) for f in raised)
            for entry in case.must_find
        ),
        # A tool that rates no severity is left out, never guessed.
        "rated": sum(f.get("severity") is not None for f, _ in hits),
        "severe_enough": sum(
            _SEVERITY_RANK[f["severity"]] >= _SEVERITY_RANK[entry.severity.value]
            for f, entry in hits
            if f.get("severity") is not None
        ),
        # Hits that quoted evidence, and of those, the ones with a verified quote
        # on the bug's own lines. A tool that quotes nothing is left out.
        "evidenced": sum(bool(f.get("evidence")) for f, _ in hits),
        "evidence_on_key": sum(
            any(q.get("verified") and entry.contains(q["file"], q["line"]) for q in f["evidence"])
            for f, entry in hits
            if f.get("evidence")
        ),
        "false_positives": false_positives,
        "duplicates": duplicates,
        "unlabeled": unlabeled,
        "correct": not review["findings"] if case.kind == "clean" else bool(hits),
        "seconds": review["seconds"],
        "cost_usd": review_cost(review.get("usage")),
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def run_metrics(scores: list[dict]) -> dict[str, float | None]:
    """Every metric for one run over a group of cases."""
    hits = sum(s["hits"] for s in scores)
    costs = [s["cost_usd"] for s in scores]
    return {
        "recall": _ratio(hits, sum(s["expected"] for s in scores)),
        "recall_before_rules": _ratio(
            sum(s["hits_before_rules"] for s in scores), sum(s["expected"] for s in scores)
        ),
        "precision": _ratio(hits, hits + sum(s["false_positives"] for s in scores)),
        "accuracy": _ratio(sum(s["correct"] for s in scores), len(scores)),
        "severity_accuracy": _ratio(
            sum(s["severe_enough"] for s in scores), sum(s["rated"] for s in scores)
        ),
        "evidence_accuracy": _ratio(
            sum(s["evidence_on_key"] for s in scores), sum(s["evidenced"] for s in scores)
        ),
        "seconds": statistics.median(s["seconds"] for s in scores),
        "cost_usd": None if None in costs else sum(costs),
        "duplicates": sum(s["duplicates"] for s in scores),
        "unlabeled": sum(len(s["unlabeled"]) for s in scores),
    }


def _spread(values: list[float | None]) -> dict[str, float] | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return {"median": statistics.median(present), "min": min(present), "max": max(present)}


def score(suite: Suite, raw_dir: Path) -> dict:
    """Score each attempt that has results under `raw_dir/<attempt id>/`."""
    attempts = {}
    for attempt in suite.attempts:
        result = score_attempt(suite, raw_dir / attempt.id)
        if result is not None:
            attempts[attempt.id] = result
    if not attempts:
        raise ValueError(f"no results for any attempt in {raw_dir}")
    return {"attempts": attempts}


def score_attempt(suite: Suite, raw_dir: Path) -> dict | None:
    """Score every case with results in `raw_dir`: each metric's median and
    min-max across runs, overall and per kind. None when there are none."""
    runs: dict[str, list[tuple[Case, dict]]] = {}
    unlabeled = []
    for case in suite.cases:
        for path in sorted((raw_dir / case.id).glob("*.json")):
            result = score_review(case, json.loads(path.read_text()))
            runs.setdefault(path.stem, []).append((case, result))
            unlabeled += [
                {"case": case.id, "run": path.stem, **{k: f.get(k) for k in _FINDING_KEYS}}
                for f in result["unlabeled"]
            ]
    if not runs:
        return None

    def group(kind: str | None) -> dict:
        per_run = [
            run_metrics(scores)
            for scores in (
                [s for case, s in pairs if kind in (None, case.kind)] for pairs in runs.values()
            )
            if scores
        ]
        return {key: _spread([m[key] for m in per_run]) for key, _, _ in _METRICS}

    kinds = sorted({case.kind for pairs in runs.values() for case, _ in pairs})
    by_case: dict[str, dict] = {}
    for pairs in runs.values():
        for case, s in pairs:
            counts = by_case.setdefault(
                case.id, {"kind": case.kind, "runs": 0, "correct": 0, "raised": 0, "posted": 0}
            )
            counts["runs"] += 1
            counts["correct"] += s["correct"]
            counts["raised"] += s["hits_before_rules"] > 0
            counts["posted"] += s["hits"] + s["false_positives"] + len(s["unlabeled"])
    return {
        "runs": len(runs),
        "cases": sorted(by_case),
        "overall": group(None),
        "by_kind": {kind: group(kind) for kind in kinds},
        "by_case": dict(sorted(by_case.items())),
        "unlabeled": unlabeled,
    }


def _format(value: float | None, style: str) -> str:
    if value is None:
        return "n/a"
    return {
        "ratio": f"{value:.2f}",
        "seconds": f"{value:.1f}",
        "usd": f"${value:.4f}",
        "count": f"{value:g}",
    }[style]


def _regressed(old: float, new: float, style: str, tolerance: float) -> bool:
    if style == "ratio":
        return new < old - tolerance
    if style in ("seconds", "usd"):
        return new > old * (1 + _SLOWER_TOLERANCE)
    return False


def _median(metrics: dict, key: str) -> float | None:
    spread = metrics.get(key)
    return spread["median"] if spread else None


def _dot(value: float | None, style: str) -> str:
    """🟢/🟡/🔴 for a ratio, so a weak score stands out; blank for the rest."""
    if style != "ratio":
        return ""
    if value is None:
        return "⚪"
    return "🟢" if value >= 0.8 else "🟡" if value >= 0.5 else "🔴"


def markdown(result: dict, baseline: dict, tolerance: float) -> str:
    """The run summary for $GITHUB_STEP_SUMMARY: every attempt side by side,
    one column each, then each attempt's details folded away."""
    attempts = result["attempts"]
    old = baseline.get("attempts", {})
    lines = [
        "## Review quality",
        "",
        "Each case is a real upstream PR with a known answer: a bug someone later fixed, "
        "or clean code with nothing to flag.",
        "",
        "🟢 0.80 or more · 🟡 0.50 or more · 🔴 below 0.50 · ⚪ not measured · "
        "⚠ worse than the baseline",
        "",
        "| Metric | "
        + " | ".join(_attempt_header(i, a) for i, a in attempts.items())
        + " | What it means |",
        "|---|" + "--:|" * len(attempts) + "---|",
    ]
    for key, label, style in _METRICS:
        cells = []
        for attempt_id, attempt in attempts.items():
            new = _median(attempt["overall"], key)
            cell = " ".join(filter(None, [_dot(new, style), _format(new, style)]))
            old_overall = old.get(attempt_id, {}).get("overall")
            if old_overall:
                before = _median(old_overall, key)
                if before is not None and new is not None:
                    if _regressed(before, new, style, tolerance):
                        cell += " ⚠"
            cells.append(cell)
        lines.append(f"| **{label}** | " + " | ".join(cells) + f" | {_MEANING[key]} |")

    cases = {
        case_id: case["kind"]
        for attempt in attempts.values()
        for case_id, case in attempt.get("by_case", {}).items()
    }
    if cases:
        lines += [
            "",
            "| Case | Kind | " + " | ".join(f"`{i}`" for i in attempts) + " |",
            "|---|---|" + ":-:|" * len(attempts),
        ]
        for case_id, kind in sorted(cases.items()):
            cells = [_case_cell(a.get("by_case", {}).get(case_id)) for a in attempts.values()]
            lines.append(f"| `{case_id}` | {kind} | " + " | ".join(cells) + " |")
        lines += [
            "",
            "✅ caught, or quiet on a clean case · 🟡 raised but dropped by the confidence "
            "threshold, or caught in only some runs · ❌ missed, or findings on a clean case",
        ]
    for attempt_id, attempt in attempts.items():
        lines += ["", *_attempt_details(attempt_id, attempt, old.get(attempt_id, {}))]
    return "\n".join(lines)


def _attempt_header(attempt_id: str, attempt: dict) -> str:
    runs = attempt["runs"]
    return f"`{attempt_id}` ({runs} run{'s' * (runs > 1)})"


def _case_cell(case: dict | None) -> str:
    """One case's outcome for one attempt, across its runs."""
    if case is None:
        return "—"
    runs, correct = case["runs"], case["correct"]
    of = f" {correct}/{runs}" if runs > 1 else ""
    if case["kind"] == "clean":
        if correct == runs:
            return "✅ quiet"
        return f"❌ {case['posted']} findings" + (f", quiet{of}" if correct else "")
    if correct == runs:
        return "✅ caught"
    if correct:
        return f"🟡 caught{of}"
    if case["raised"]:
        raised = f" {case['raised']}/{runs}" if runs > 1 else ""
        return f"🟡 raised{raised}, filtered"
    return "❌ missed"


def _attempt_details(attempt_id: str, result: dict, baseline: dict) -> list[str]:
    """Baseline, range and unlabeled findings for one attempt, folded."""
    runs = result["runs"]
    old_overall = baseline.get("overall")
    summary = f"`{attempt_id}`: {len(result['cases'])} cases × {runs} run{'s' * (runs > 1)}"
    lines = [f"<details><summary>{summary}, baseline and details</summary>", ""]
    if not old_overall:
        lines += ["No baseline yet.", ""]
    columns = ["Metric", "Now", "Baseline", *(["Range"] * (runs > 1))]
    lines += ["| " + " | ".join(columns) + " |", "|---" + "|--:" * (len(columns) - 1) + "|"]
    for key, label, style in _METRICS:
        new = _median(result["overall"], key)
        before = _median(old_overall, key) if old_overall else None
        cells = [label, _format(new, style), _format(before, style) if old_overall else "—"]
        if runs > 1:
            spread = result["overall"][key]
            cells.append(
                f"{_format(spread['min'], style)}–{_format(spread['max'], style)}" if spread else ""
            )
        lines.append("| " + " | ".join(cells) + " |")
    if result["unlabeled"]:
        lines += [
            "",
            f"{len(result['unlabeled'])} unlabeled findings to judge:",
            "",
            *(
                f"- `{f['case']}` run {f['run']}: `{f['file']}:{f['line']}` "
                f"{f['severity']}, {f['confidence']}: {f['message']}"
                for f in result["unlabeled"]
            ),
        ]
    return [*lines, "", "</details>"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, default=HERE / "raw", help="run.py's output dir")
    parser.add_argument("--cases", type=Path, default=HERE / "cases.yml")
    parser.add_argument("--baseline", type=Path, default=HERE / "baseline.json")
    parser.add_argument("--out", type=Path, default=HERE / "score.json")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="warn when a ratio metric drops by more than this (default 0.05)",
    )
    args = parser.parse_args(argv)
    try:
        result = score(load_suite(args.cases), args.raw)
        baseline = json.loads(args.baseline.read_text())
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
        print(f"score.py: broken input: {error}", file=sys.stderr)
        return 2
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(markdown(result, baseline, args.tolerance))
    return 0


if __name__ == "__main__":
    sys.exit(main())
