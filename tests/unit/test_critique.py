from unittest.mock import AsyncMock, patch

import pytest
from conftest import working_tree_file

from marginal.cli import main
from marginal.cli.critique import _build_critique_prompt, _Critique, _CritiqueResponse
from marginal.cli.review import (
    _build_finding_prompt,
    _estimate_tokens,
    _FindingsResponse,
    _redact_patches,
)
from marginal.providers.errors import ProviderResponseError
from marginal.review import Finding, Severity

PATCH = "@@ -1,2 +1,3 @@\n import time\n+time.sleep(1)\n retry()"
FILES = [{"filename": "retry.py", "patch": PATCH}]


def _finding(message, confidence=0.9, line=2):
    return Finding(
        file="retry.py", line=line, severity=Severity.MEDIUM, confidence=confidence, message=message
    )


FINDINGS = [
    _finding("Sleep blocks the loop."),
    _finding("Retry is unbounded.", line=3),
    _finding("Import is unused.", confidence=0.6, line=1),
]


def _verdicts(*results):
    return _CritiqueResponse(
        results=[_Critique(id=id, drop=drop, confidence=c, reason="r") for id, drop, c in results]
    )


@pytest.fixture
def provider(tmp_path, monkeypatch):
    """Run `marginal review` in `tmp_path` against a mocked PR and one model mock
    shared by generation and critique; yields `generate_structured`."""
    monkeypatch.chdir(tmp_path)
    with (
        patch("marginal.cli.review.GitHubClient") as client_cls,
        patch("marginal.cli.review.get_provider") as get_provider,
        patch("marginal.cli.critique.get_provider", get_provider),
    ):
        client = client_cls.return_value
        client.get_file.side_effect = working_tree_file
        client.get_pull_request.return_value = {
            "title": "Retry",
            "state": "open",
            "base": {"sha": "abc"},
            "head": {"sha": "def"},
        }
        client.get_pull_request_files.return_value = FILES
        client.list_review_comments.return_value = []
        get_provider.return_value.generate_structured = AsyncMock()
        yield get_provider.return_value.generate_structured


def _config(tmp_path, *, self_reflect, max_prompt_tokens=100_000):
    (tmp_path / ".marginal").mkdir()
    (tmp_path / ".marginal" / "config.yaml").write_text(
        "version: 1\n"
        "models:\n  reviewer:\n    provider: anthropic\n    model: claude-sonnet-5\n"
        f"review:\n  self_reflect: {str(self_reflect).lower()}\n"
        f"  confidence_threshold: 0.85\n  max_prompt_tokens: {max_prompt_tokens}\n"
    )


def _review(provider, *answers):
    provider.side_effect = [_FindingsResponse(findings=FINDINGS), *answers]
    return main(["review", "--repo", "acme/widgets", "--pr", "42"])


def test_off_by_default_makes_one_model_call(tmp_path, provider, capsys):
    _config(tmp_path, self_reflect=False)

    assert _review(provider) == 0

    provider.assert_awaited_once()
    out = capsys.readouterr().out
    assert "Sleep blocks the loop." in out
    assert "Retry is unbounded." in out
    assert "Import is unused." not in out  # 60% is under the 0.85 threshold


def test_critique_rescores_and_drops_before_filtering(tmp_path, provider, capsys):
    _config(tmp_path, self_reflect=True)

    exit_code = _review(provider, _verdicts((1, True, 0.9), (2, False, 0.5), (3, False, 0.6)))

    assert exit_code == 0
    assert provider.await_count == 2
    captured = capsys.readouterr()
    assert "Sleep blocks the loop." not in captured.out  # dropped
    assert "Retry is unbounded." not in captured.out  # re-scored under the threshold
    assert "self-critique dropped 1 of 3 finding(s)" in captured.err


def test_the_critique_can_never_raise_a_confidence(tmp_path, provider, capsys):
    _config(tmp_path, self_reflect=True)

    _review(provider, _verdicts((1, False, 1.0), (3, False, 0.95)))

    out = capsys.readouterr().out
    assert "Sleep blocks the loop." in out
    assert "90% confidence" in out  # kept its first-pass 0.9, not 1.0
    assert "100% confidence" not in out
    assert "Import is unused." not in out  # 0.6 stays under the 0.85 threshold


def test_a_finding_the_critique_leaves_out_is_kept_unchanged(tmp_path, provider, capsys):
    _config(tmp_path, self_reflect=True)

    _review(provider, _verdicts((2, True, 0.0), (99, True, 0.0)))

    out = capsys.readouterr().out
    assert "Sleep blocks the loop." in out
    assert "90% confidence" in out
    assert "Retry is unbounded." not in out


def test_a_failed_critique_keeps_the_findings_and_the_review(tmp_path, provider, capsys):
    _config(tmp_path, self_reflect=True)

    exit_code = _review(provider, ProviderResponseError("overloaded"))

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Sleep blocks the loop." in captured.out
    assert "Retry is unbounded." in captured.out
    assert "self-critique failed, keeping findings as-is: overloaded" in captured.err


def test_an_over_budget_critique_calls_no_model(tmp_path, provider, capsys):
    generation = _estimate_tokens(_build_finding_prompt(_redact_patches(FILES), [], [], "."))
    assert _estimate_tokens(_build_critique_prompt(FINDINGS, FILES)) > generation
    _config(tmp_path, self_reflect=True, max_prompt_tokens=generation)

    assert _review(provider) == 0

    provider.assert_awaited_once()
    captured = capsys.readouterr()
    assert "Sleep blocks the loop." in captured.out
    assert "skipped self-critique" in captured.err


def test_no_findings_means_no_critique_call(tmp_path, provider):
    _config(tmp_path, self_reflect=True)
    provider.return_value = _FindingsResponse(findings=[])

    assert main(["review", "--repo", "acme/widgets", "--pr", "42"]) == 0

    provider.assert_awaited_once()


def test_the_critique_prompt_numbers_each_finding_and_carries_the_diff(tmp_path, provider):
    _config(tmp_path, self_reflect=True)

    _review(provider, _verdicts())

    prompt = provider.await_args.args[0]
    assert "--- finding 1 at retry.py:2 · medium · 90% confidence ---\nSleep blocks" in prompt
    assert "--- finding 3 at retry.py:1 · medium · 60% confidence ---\nImport is" in prompt
    assert f"--- retry.py ---\n{PATCH}" in prompt
    assert "code between hunks" in prompt
