from unittest.mock import patch

import pytest

from marginal.cli import main
from marginal.config import MarginalConfig, load_config
from marginal.github.errors import (
    GitHubAPIError,
    GitHubAuthenticationError,
    GitHubNotFoundError,
    PermissionDeniedError,
)


def test_init_creates_all_artifacts(tmp_path, capsys):
    exit_code = main(["init", str(tmp_path)])

    assert exit_code == 0
    assert (tmp_path / ".marginal" / "config.yaml").is_file()
    assert (tmp_path / ".marginal" / "policies").is_dir()
    assert (tmp_path / ".github" / "workflows" / "marginal.yml").is_file()

    out = capsys.readouterr().out
    assert "✓ Created .marginal/config.yaml" in out
    assert "✓ Created .marginal/policies/" in out
    assert "✓ Created .github/workflows/marginal.yml" in out
    assert "marginal is ready." in out


def test_init_defaults_to_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    exit_code = main(["init"])

    assert exit_code == 0
    assert (tmp_path / ".marginal" / "config.yaml").is_file()


def test_rerun_skips_existing_artifacts(tmp_path, capsys):
    main(["init", str(tmp_path)])
    capsys.readouterr()

    exit_code = main(["init", str(tmp_path)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "- Skipped .marginal/config.yaml (already exists)" in out
    assert "- Skipped .marginal/policies/ (already exists)" in out
    assert "- Skipped .github/workflows/marginal.yml (already exists)" in out


def test_rerun_does_not_clobber_a_customized_config(tmp_path):
    main(["init", str(tmp_path)])
    config_path = tmp_path / ".marginal" / "config.yaml"
    config_path.write_text("version: 1\nreview:\n  tone: strict\n")

    main(["init", str(tmp_path)])

    assert config_path.read_text() == "version: 1\nreview:\n  tone: strict\n"


def test_force_overwrites_existing_artifacts(tmp_path, capsys):
    main(["init", str(tmp_path)])
    config_path = tmp_path / ".marginal" / "config.yaml"
    config_path.write_text("version: 1\nreview:\n  tone: strict\n")

    exit_code = main(["init", str(tmp_path), "--force"])

    assert exit_code == 0
    assert config_path.read_text() != "version: 1\nreview:\n  tone: strict\n"
    out = capsys.readouterr().out
    assert "✓ Created .marginal/config.yaml" in out
    assert "✓ Created .marginal/policies/" in out
    assert "✓ Created .github/workflows/marginal.yml" in out


def test_generated_config_round_trips_through_load_config(tmp_path):
    main(["init", str(tmp_path)])

    assert load_config(tmp_path) == MarginalConfig()


# -- review ------------------------------------------------------------


def test_review_prints_pr_summary_and_posts_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with patch("marginal.cli.review.GitHubClient") as mock_client_cls:
        client = mock_client_cls.return_value
        client.get_pull_request.return_value = {
            "title": "Fix flaky retry logic",
            "state": "open",
            "base": {"sha": "abc123"},
            "head": {"sha": "def456"},
        }
        client.get_pull_request_files.return_value = [
            {"filename": "marginal/retry.py"},
            {"filename": "tests/test_retry.py"},
        ]

        exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 0
    args, _ = mock_client_cls.call_args
    assert args[0] == "acme/widgets"

    out = capsys.readouterr().out
    assert "PR #42: Fix flaky retry logic" in out
    assert "State: open" in out
    assert "Base: abc123  Head: def456" in out
    assert "Files changed: 2" in out
    assert "marginal/retry.py" in out
    assert "tests/test_retry.py" in out
    client.create_review.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        PermissionDeniedError("this operation requires permissions.read.pull_requests"),
        GitHubAuthenticationError(
            "the GitHub client requires the GITHUB_TOKEN environment variable to be set"
        ),
        GitHubAPIError(500, "Internal Server Error"),
        GitHubNotFoundError(404, "Not Found"),
    ],
    ids=["permission-denied", "auth-error", "api-error", "not-found"],
)
def test_review_prints_clean_message_on_error(tmp_path, capsys, monkeypatch, error):
    monkeypatch.chdir(tmp_path)

    with patch("marginal.cli.review.GitHubClient") as mock_client_cls:
        mock_client_cls.return_value.get_pull_request.side_effect = error

        exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "marginal review:" in err
    assert "Traceback" not in err
