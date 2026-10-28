"""Tests of run.py's per-attempt setup with the review stubbed: no network, no model."""

import json

import pytest
import run
import yaml
from score import Attempt, Case


def test_run_attempt_reviews_with_the_attempts_model_and_saves_under_its_id(tmp_path, monkeypatch):
    seen = []

    def fake_review(attempt, case, checkout):
        seen.append(yaml.safe_load((checkout / ".marginal" / "config.yaml").read_text()))
        return {"findings": [], "seconds": 1.0}

    monkeypatch.setattr(run, "review", fake_review)
    checkout = tmp_path / "checkout"
    (checkout / ".marginal").mkdir(parents=True)
    attempt = Attempt(tool="marginal", provider="openai", model="gpt-5.5")
    case = Case(
        id="clean-refactor",
        upstream="owner/repo",
        base="a" * 40,
        head="b" * 40,
        kind="clean",
        source="https://github.com/owner/repo/pull/1",
    )

    failures = run.run_attempt(attempt, case, checkout, {"version": 1}, 2, tmp_path / "raw")

    assert failures == 0
    assert (
        seen
        == [{"version": 1, "models": {"reviewer": {"provider": "openai", "model": "gpt-5.5"}}}] * 2
    )
    saved = tmp_path / "raw" / "marginal" / "openai" / "gpt-5.5" / "clean-refactor"
    assert sorted(p.name for p in saved.iterdir()) == ["1.json", "2.json"]
    assert json.loads((saved / "1.json").read_text())["seconds"] == 1.0


def test_pr_agent_result_reads_key_issues_without_guessing_severity():
    attempt = Attempt(tool="pr-agent", provider="anthropic", model="claude-opus-5-5")
    data = {
        "review": {
            "key_issues_to_review": [
                {
                    "relevant_file": "mlflow/server/handlers.py ",
                    "issue_header": "Possible Bug",
                    "issue_content": "max_results is never None.",
                    "start_line": 1172,
                    "end_line": "1175",
                },
                {"relevant_file": "a.py", "issue_content": "no lines given"},
            ]
        },
        "usage": {"prompt_tokens": 900, "completion_tokens": 120, "total_tokens": 1020},
    }

    result = run.pr_agent_result(data, attempt)

    assert result["findings"] == [
        {
            "file": "mlflow/server/handlers.py",
            "line": 1172,
            "end_line": 1175,
            "severity": None,
            "confidence": None,
            "message": "Possible Bug: max_results is never None.",
        },
        {
            "file": "a.py",
            "line": None,
            "end_line": None,
            "severity": None,
            "confidence": None,
            "message": "no lines given",
        },
    ]
    assert result["usage"] == {
        "model": "anthropic:claude-opus-5-5",
        "input_tokens": 900,
        "output_tokens": 120,
    }
    # A review with no key issues, and no usage reported.
    empty = run.pr_agent_result({"review": {"key_issues_to_review": []}}, attempt)
    assert empty["findings"] == []
    assert empty["usage"]["input_tokens"] is None


def test_pr_agent_never_reads_an_earlier_runs_review(tmp_path, monkeypatch):
    work = tmp_path / "work"
    checkout = work / "repo"
    checkout.mkdir(parents=True)
    (work / "pr-agent.json").write_text('{"review": {"key_issues_to_review": []}}')
    monkeypatch.setattr(run, "download_diff", lambda case: b"diff")
    # PR-Agent failing the way it does on a credit error: exit 0, no JSON.
    monkeypatch.setattr(
        run.subprocess,
        "run",
        lambda *a, **k: run.subprocess.CompletedProcess(a, 0, stdout="credit too low", stderr=""),
    )
    attempt = Attempt(tool="pr-agent", provider="anthropic", model="claude-opus-5-5")
    case = Case(
        id="clean-refactor",
        upstream="owner/repo",
        base="a" * 40,
        head="b" * 40,
        kind="clean",
        source="https://github.com/owner/repo/pull/1",
    )

    with pytest.raises(RuntimeError, match="credit too low"):
        run.review_with_pr_agent(attempt, case, checkout)
