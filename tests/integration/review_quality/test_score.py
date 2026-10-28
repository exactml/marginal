"""Tests of the benchmark scorer with hand-made findings: no network, no model."""

import json

import pytest
from pydantic import ValidationError
from score import HERE, Case, load_suite, main, markdown, review_cost, score, score_review

# $4 / $20 per million input / output tokens.
MODEL = "anthropic:claude-opus-5-5"


def bug_case(**overrides) -> Case:
    fields = {
        "id": "unchecked-path",
        "upstream": "owner/repo",
        "base": "a" * 40,
        "head": "b" * 40,
        "kind": "security",
        "source": "https://github.com/owner/repo/pull/1",
        "must_find": [{"file": "app.py", "lines": [10, 20], "severity": "high"}],
        "must_not_flag": [{"file": "app.py", "lines": [1, 5]}],
    }
    return Case.model_validate(fields | overrides)


def clean_case() -> Case:
    return bug_case(id="clean-refactor", kind="clean", must_find=[], must_not_flag=[])


def finding(file="app.py", line=12, severity="high", message="bug") -> dict:
    return {"file": file, "line": line, "severity": severity, "confidence": 0.9, "message": message}


def review(*findings, seconds=10.0, usage=None) -> dict:
    return {"findings": list(findings), "seconds": seconds, "usage": usage}


def test_classifies_hit_duplicate_false_positive_and_unlabeled():
    result = score_review(
        bug_case(),
        review(
            finding(line=12),
            finding(line=15, message="same bug again"),
            finding(line=3),
            finding(line=40),
            finding(file="other.py", line=12),
            finding(line=None),
        ),
    )

    assert result["hits"] == 1
    assert result["duplicates"] == 1
    assert result["false_positives"] == 1
    assert [(f["file"], f["line"]) for f in result["unlabeled"]] == [
        ("app.py", 40),
        ("other.py", 12),
        ("app.py", None),
    ]
    assert result["correct"]


def test_bug_case_without_a_hit_is_wrong():
    assert not score_review(bug_case(), review(finding(line=40)))["correct"]


def test_any_finding_on_a_clean_case_is_a_false_positive():
    result = score_review(clean_case(), review(finding(line=None), finding(line=3)))

    assert result["false_positives"] == 2
    assert result["unlabeled"] == []
    assert not result["correct"]
    assert score_review(clean_case(), review())["correct"]


def test_severity_below_expected_is_counted():
    assert score_review(bug_case(), review(finding(severity="critical")))["severe_enough"] == 1
    assert score_review(bug_case(), review(finding(severity="medium")))["severe_enough"] == 0


def test_cost_is_never_guessed():
    usage = {"model": MODEL, "input_tokens": 1_000_000, "output_tokens": 100_000}

    assert review_cost(usage) == pytest.approx(6.0)
    assert review_cost(usage | {"model": "ollama:llama3"}) is None
    assert review_cost(usage | {"output_tokens": None}) is None
    assert review_cost(None) is None


def write_raw(raw, case_id, run, data):
    (raw / case_id).mkdir(parents=True, exist_ok=True)
    (raw / case_id / f"{run}.json").write_text(json.dumps(data))


@pytest.fixture
def suite(tmp_path):
    cases = tmp_path / "cases.yml"
    cases.write_text(
        json.dumps(
            {
                "config": "marginal-config.yaml",
                "cases": [bug_case().model_dump(mode="json"), clean_case().model_dump(mode="json")],
            }
        )
    )
    return load_suite(cases)


def test_score_reports_median_and_range_across_runs(suite, tmp_path):
    raw = tmp_path / "raw"
    usage = {"model": MODEL, "input_tokens": 1_000_000, "output_tokens": 0}
    write_raw(raw, "unchecked-path", 1, review(finding(), seconds=10, usage=usage))
    write_raw(raw, "clean-refactor", 1, review(seconds=20, usage=usage))
    write_raw(raw, "unchecked-path", 2, review(finding(line=40), seconds=30, usage=usage))
    write_raw(raw, "clean-refactor", 2, review(finding(), seconds=40, usage=usage))
    write_raw(raw, "unchecked-path", 3, review(finding(), seconds=50))
    write_raw(raw, "clean-refactor", 3, review(seconds=60, usage=usage))

    result = score(suite, raw)

    assert result["runs"] == 3
    assert result["overall"]["recall"] == {"median": 1.0, "min": 0.0, "max": 1.0}
    assert result["overall"]["accuracy"] == {"median": 1.0, "min": 0.0, "max": 1.0}
    # Run 2 has no hit and one false positive, so precision is 0.
    assert result["overall"]["precision"] == {"median": 1.0, "min": 0.0, "max": 1.0}
    assert result["overall"]["seconds"] == {"median": 35.0, "min": 15.0, "max": 55.0}
    # Run 3 has a review without usage: its cost is unknown, not zero.
    assert result["overall"]["cost_usd"] == {"median": 8.0, "min": 8.0, "max": 8.0}
    assert result["by_kind"]["clean"]["recall"] is None
    assert result["by_kind"]["clean"]["accuracy"]["min"] == 0.0
    assert result["unlabeled"] == [
        {"case": "unchecked-path", "run": "2"} | finding(line=40),
    ]


def result_with(recall: float, seconds: float) -> dict:
    spread = lambda v: {"median": v, "min": v, "max": v}  # noqa: E731
    metrics = {
        "recall": spread(recall),
        "precision": spread(1.0),
        "accuracy": spread(1.0),
        "severity_accuracy": None,
        "seconds": spread(seconds),
        "cost_usd": None,
        "duplicates": spread(0),
        "unlabeled": spread(0),
    }
    return {"runs": 3, "cases": ["x"], "overall": metrics, "by_kind": {}, "unlabeled": []}


def test_markdown_without_baseline():
    text = markdown(result_with(1.0, 10.0), {}, tolerance=0.05)

    assert "No baseline yet." in text
    assert "| Recall | 1.00 | 1.00–1.00 |" in text


def test_markdown_warns_only_on_regressions_beyond_tolerance():
    old = result_with(1.0, 10.0)

    text = markdown(result_with(0.5, 20.0), old, tolerance=0.05)
    assert "| Recall | 1.00 → 0.50 ⚠ |" in text
    assert "| Time (median s per review) | 10.0 → 20.0 ⚠ |" in text

    text = markdown(result_with(0.97, 11.0), old, tolerance=0.05)
    assert "⚠" not in text


def test_main_writes_score_and_fails_only_on_broken_input(suite, tmp_path, capsys):
    cases = tmp_path / "cases.yml"
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(result_with(1.0, 1.0)))
    raw = tmp_path / "raw"
    write_raw(raw, "unchecked-path", 1, review(seconds=100))
    out = tmp_path / "score.json"
    args = ["--cases", str(cases), "--raw", str(raw), "--baseline", str(baseline)]

    # A regression still exits 0: the gate is soft.
    assert main([*args, "--out", str(out)]) == 0
    assert "⚠" in capsys.readouterr().out
    assert json.loads(out.read_text())["runs"] == 1

    assert main([*args, "--raw", str(tmp_path / "missing"), "--out", str(out)]) == 2


def test_answer_key_must_fit_the_kind():
    with pytest.raises(ValidationError):
        bug_case(must_find=[])
    with pytest.raises(ValidationError):
        bug_case(kind="clean")
    with pytest.raises(ValidationError):
        bug_case(must_not_flag=[{"file": "app.py", "lines": [5, 1]}])


def test_shipped_cases_are_valid():
    suite = load_suite(HERE / "cases.yml")

    assert (HERE / suite.config).is_file()
