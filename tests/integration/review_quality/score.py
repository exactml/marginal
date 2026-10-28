"""Score review-quality benchmark runs against the answer key in cases.yml.

Reads `raw/<case-id>/<run>.json` -- one `marginal review --format json`
output each, plus the wall-clock `seconds` run.py adds -- writes score.json,
and prints a Markdown comparison with baseline.json for the CI run summary.
A regression only gets a warning: the exit code is non-zero for broken input
alone, never for a worse score.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from marginal.review import Severity

HERE = Path(__file__).parent

_SEVERITY_RANK = {severity.value: rank for rank, severity in enumerate(Severity)}

# (key, label, how it's formatted and when a change counts as a regression)
_METRICS = [
    ("recall", "Recall", "ratio"),
    ("precision", "Precision", "ratio"),
    ("accuracy", "Accuracy (per PR)", "ratio"),
    ("severity_accuracy", "Severity accuracy", "ratio"),
    ("seconds", "Time (median s per review)", "seconds"),
    ("cost_usd", "Cost (USD per run)", "usd"),
    ("duplicates", "Duplicate findings", "count"),
    ("unlabeled", "Unlabeled findings", "count"),
]
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

    def contains(self, file: str, line: int | None) -> bool:
        return line is not None and file == self.file and self.lines[0] <= line <= self.lines[1]


class Expected(Location):
    severity: Severity


class Case(_Strict):
    id: str = Field(min_length=1)
    upstream: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    base: str = Field(min_length=7)
    head: str = Field(min_length=7)
    kind: Literal["security", "dependency", "caller", "logic", "test", "clean"]
    source: str
    evidence: str | None = None
    must_find: list[Expected] = Field(default_factory=list)
    must_not_flag: list[Location] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_answer_key(self) -> Case:
        if (self.kind == "clean") == bool(self.must_find):
            raise ValueError(
                f"{self.id}: a clean case has no must_find; every other kind needs one"
            )
        return self


class Price(_Strict):
    """USD per million tokens."""

    input: float = Field(ge=0)
    output: float = Field(ge=0)


class Suite(_Strict):
    config: str
    prices: dict[str, Price] = Field(default_factory=dict)
    cases: list[Case]

    @model_validator(mode="after")
    def _check_unique_ids(self) -> Suite:
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate case ids in {ids}")
        return self


def load_suite(path: Path) -> Suite:
    return Suite.model_validate(yaml.safe_load(path.read_text()))


def review_cost(usage: dict | None, prices: dict[str, Price]) -> float | None:
    """The review's cost in USD, or None when the model or a token count is
    unknown -- a missing price is never guessed."""
    usage = usage or {}
    price = prices.get(usage.get("model"))
    tokens_in, tokens_out = usage.get("input_tokens"), usage.get("output_tokens")
    if price is None or tokens_in is None or tokens_out is None:
        return None
    return (tokens_in * price.input + tokens_out * price.output) / 1_000_000


def score_review(case: Case, review: dict, prices: dict[str, Price]) -> dict:
    """Match one review's findings against the case's answer key.

    Each must_find entry is hit at most once, by the first finding inside its
    range; later findings there are duplicates, not false positives.
    """
    hit_by: list[dict | None] = [None] * len(case.must_find)
    false_positives = duplicates = 0
    unlabeled = []
    for finding in review["findings"]:
        file, line = finding["file"], finding["line"]
        matched = [i for i, entry in enumerate(case.must_find) if entry.contains(file, line)]
        if matched:
            free = [i for i in matched if hit_by[i] is None]
            if free:
                hit_by[free[0]] = finding
            else:
                duplicates += 1
        elif case.kind == "clean" or any(loc.contains(file, line) for loc in case.must_not_flag):
            false_positives += 1
        else:
            unlabeled.append(finding)
    hits = [(f, entry) for f, entry in zip(hit_by, case.must_find, strict=True) if f is not None]
    return {
        "expected": len(case.must_find),
        "hits": len(hits),
        "severe_enough": sum(
            _SEVERITY_RANK[f["severity"]] >= _SEVERITY_RANK[entry.severity.value]
            for f, entry in hits
        ),
        "false_positives": false_positives,
        "duplicates": duplicates,
        "unlabeled": unlabeled,
        "correct": not review["findings"] if case.kind == "clean" else bool(hits),
        "seconds": review["seconds"],
        "cost_usd": review_cost(review.get("usage"), prices),
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def run_metrics(scores: list[dict]) -> dict[str, float | None]:
    """Every metric for one run over a group of cases."""
    hits = sum(s["hits"] for s in scores)
    costs = [s["cost_usd"] for s in scores]
    return {
        "recall": _ratio(hits, sum(s["expected"] for s in scores)),
        "precision": _ratio(hits, hits + sum(s["false_positives"] for s in scores)),
        "accuracy": _ratio(sum(s["correct"] for s in scores), len(scores)),
        "severity_accuracy": _ratio(sum(s["severe_enough"] for s in scores), hits),
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
    """Score every case with results in `raw_dir`: each metric's median and
    min-max across runs, overall and per kind."""
    runs: dict[str, list[tuple[Case, dict]]] = {}
    unlabeled = []
    for case in suite.cases:
        for path in sorted((raw_dir / case.id).glob("*.json")):
            result = score_review(case, json.loads(path.read_text()), suite.prices)
            runs.setdefault(path.stem, []).append((case, result))
            unlabeled += [
                {"case": case.id, "run": path.stem, **{k: f.get(k) for k in _FINDING_KEYS}}
                for f in result["unlabeled"]
            ]
    if not runs:
        raise ValueError(f"no results for any case in {raw_dir}")

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
    return {
        "runs": len(runs),
        "cases": sorted({case.id for pairs in runs.values() for case, _ in pairs}),
        "overall": group(None),
        "by_kind": {kind: group(kind) for kind in kinds},
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


def markdown(result: dict, baseline: dict, tolerance: float) -> str:
    """The comparison with the baseline, for $GITHUB_STEP_SUMMARY."""
    lines = [
        "## Review quality",
        "",
        f"{len(result['cases'])} cases × {result['runs']} runs; median across runs, "
        "with the min-max range.",
        "",
    ]
    old_overall = baseline.get("overall")
    if not old_overall:
        lines += ["No baseline yet.", ""]
    header = "Baseline → now" if old_overall else "Now"
    lines += [f"| Metric | {header} | Range |", "|---|---|---|"]
    for key, label, style in _METRICS:
        spread = result["overall"][key]
        new = _median(result["overall"], key)
        cell = _format(new, style)
        if old_overall:
            old = _median(old_overall, key)
            cell = f"{_format(old, style)} → {cell}"
            if old is not None and new is not None and _regressed(old, new, style, tolerance):
                cell += " ⚠"
        span = f"{_format(spread['min'], style)}–{_format(spread['max'], style)}" if spread else ""
        lines.append(f"| {label} | {cell} | {span} |")

    ratio_metrics = [(key, label) for key, label, style in _METRICS if style == "ratio"]
    lines += [
        "",
        "| Kind | " + " | ".join(label for _, label in ratio_metrics) + " |",
        "|---" * (len(ratio_metrics) + 1) + "|",
    ]
    for kind, metrics in result["by_kind"].items():
        cells = [_format(_median(metrics, key), "ratio") for key, _ in ratio_metrics]
        lines.append(f"| {kind} | " + " | ".join(cells) + " |")
    if result["unlabeled"]:
        lines += [
            "",
            f"{len(result['unlabeled'])} unlabeled findings are listed in score.json "
            "for a person to judge.",
        ]
    return "\n".join(lines)


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
