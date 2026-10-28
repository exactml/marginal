"""Tests of run.py's per-attempt setup with the review stubbed: no network, no model."""

import json

import run
import yaml
from score import Attempt, Case


def test_run_attempt_reviews_with_the_attempts_model_and_saves_under_its_id(tmp_path, monkeypatch):
    seen = []

    def fake_review(case, checkout):
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
