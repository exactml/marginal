from unittest.mock import patch

import pytest
import requests

from marginal.cli import main
from marginal.github.errors import GitHubAPIError, GitHubAuthenticationError, GitHubNotFoundError

REVIEWER = "models:\n  reviewer:\n    provider: anthropic\n    model: claude-sonnet-5\n"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repo where every check passes; tests break one thing each."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".marginal").mkdir()
    (tmp_path / ".marginal" / "config.yaml").write_text(f"version: 1\n{REVIEWER}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    with patch("marginal.cli.doctor.GitHubClient") as cls:
        yield cls


def _write_config(tmp_path, text):
    (tmp_path / ".marginal" / "config.yaml").write_text(text)


def test_all_checks_pass(repo, capsys):
    exit_code = main(["doctor", "--repo", "acme/widgets"])

    assert exit_code == 0
    assert capsys.readouterr().out == (
        "✓ .marginal/config.yaml is valid\n"
        "✓ models.reviewer: anthropic / claude-sonnet-5 is ready\n"
        "✓ permissions allow `marginal review --comment`\n"
        "✓ GITHUB_TOKEN is set\n"
        "✓ GitHub accepted GITHUB_TOKEN and acme/widgets is reachable\n"
        "\n"
        "All checks passed.\n"
    )
    repo.assert_called_once()
    assert repo.call_args.args[0] == "acme/widgets"
    repo.return_value.get_repository.assert_called_once_with()


def test_without_repo_skips_the_github_call_and_still_passes(repo, capsys):
    exit_code = main(["doctor"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "- Skipped GitHub access (pass --repo owner/name to check it)\n" in out
    repo.assert_not_called()


def test_missing_config_points_at_init(repo, tmp_path, capsys):
    (tmp_path / ".marginal" / "config.yaml").unlink()

    exit_code = main(["doctor"])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "✗ .marginal/config.yaml not found\n    → run `marginal init` to scaffold it\n" in out
    assert "models." not in out
    assert "1 check(s) failed." in out


def test_invalid_config_names_the_field_without_a_traceback(repo, tmp_path, capsys):
    _write_config(tmp_path, f"version: 1\n{REVIEWER}review:\n  max_comments: 0\n")

    exit_code = main(["doctor"])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "✗ " in out and "review.max_comments" in out
    assert "Traceback" not in out


def test_invalid_yaml_is_reported(repo, tmp_path, capsys):
    _write_config(tmp_path, "version: [1\n")

    assert main(["doctor"]) == 1
    assert "invalid YAML" in capsys.readouterr().out


def test_missing_reviewer_is_reported(repo, tmp_path, capsys):
    _write_config(tmp_path, "version: 1\n")

    exit_code = main(["doctor"])

    assert exit_code == 1
    assert "✗ models.reviewer is not set\n" in capsys.readouterr().out


@pytest.mark.parametrize("value", [None, ""])
def test_missing_or_empty_provider_key_is_reported_by_name(repo, monkeypatch, capsys, value):
    if value is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY")
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", value)

    exit_code = main(["doctor"])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "✗ models.reviewer: " in out and "ANTHROPIC_API_KEY" in out
    assert "repository secret" in out


def test_every_configured_model_is_checked(repo, tmp_path, capsys):
    _write_config(
        tmp_path,
        f"version: 1\n{REVIEWER}  planner:\n    provider: openai\n    model: gpt-5\n",
    )

    exit_code = main(["doctor"])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "✓ models.reviewer:" in out
    assert "✗ models.planner: " in out and "OPENAI_API_KEY" in out


def test_unknown_provider_is_reported(repo, tmp_path, capsys):
    _write_config(tmp_path, "version: 1\nmodels:\n  reviewer:\n    provider: acme\n    model: x\n")

    assert main(["doctor"]) == 1
    assert "✗ models.reviewer: unsupported model provider 'acme'" in capsys.readouterr().out


@pytest.mark.parametrize(
    "permissions, flag",
    [
        ("read:\n    pull_requests: false", "permissions.read.pull_requests"),
        ("write:\n    comments: false", "permissions.write.comments"),
    ],
)
def test_permissions_that_block_review_comment_are_reported(
    repo, tmp_path, capsys, permissions, flag
):
    _write_config(tmp_path, f"version: 1\n{REVIEWER}permissions:\n  {permissions}\n")

    exit_code = main(["doctor"])

    assert exit_code == 1
    assert f"✗ {flag} off, so `marginal review --comment` can't run\n" in capsys.readouterr().out


def test_missing_github_token_skips_the_github_call(repo, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN")

    exit_code = main(["doctor", "--repo", "acme/widgets"])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "✗ GITHUB_TOKEN is not set\n" in out
    assert "reachable" not in out
    repo.assert_not_called()


@pytest.mark.parametrize(
    "error, line",
    [
        (GitHubAuthenticationError("rejected"), "✗ GitHub rejected GITHUB_TOKEN\n"),
        (GitHubNotFoundError(404, "Not Found"), "✗ acme/widgets not found, or GITHUB_TOKEN"),
        (GitHubAPIError(500, "boom"), "✗ GitHub check for acme/widgets failed: GitHub API error"),
        (requests.ConnectionError("no route"), "✗ couldn't reach GitHub: no route\n"),
    ],
)
def test_github_failures_are_reported(repo, capsys, error, line):
    repo.return_value.get_repository.side_effect = error

    exit_code = main(["doctor", "--repo", "acme/widgets"])

    assert exit_code == 1
    assert line in capsys.readouterr().out


def test_help_doctor_prints_its_usage(capsys):
    assert main(["help", "doctor"]) == 0
    assert "usage: marginal doctor" in capsys.readouterr().out
