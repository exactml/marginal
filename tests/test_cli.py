from unittest.mock import AsyncMock, patch

import pytest

from marginal.cli import main
from marginal.cli.review import _build_inline_comments
from marginal.config import MarginalConfig, load_config
from marginal.github.errors import (
    GitHubAPIError,
    GitHubAuthenticationError,
    GitHubNotFoundError,
    PermissionDeniedError,
)
from marginal.providers.errors import MissingCredentialsError
from marginal.review import Finding, Severity


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


def test_review_with_comment_flag_posts_the_printed_summary(tmp_path, capsys, monkeypatch):
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

        exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42", "--comment"])

    assert exit_code == 0
    out = capsys.readouterr().out

    client.create_review.assert_called_once_with(42, out.rstrip("\n"), event="COMMENT", comments=[])


def test_review_without_comment_flag_posts_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with patch("marginal.cli.review.GitHubClient") as mock_client_cls:
        client = mock_client_cls.return_value
        client.get_pull_request.return_value = {
            "title": "Fix flaky retry logic",
            "state": "open",
            "base": {"sha": "abc123"},
            "head": {"sha": "def456"},
        }
        client.get_pull_request_files.return_value = []

        exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 0
    client.create_review.assert_not_called()


def test_review_with_comment_flag_maps_permission_denied_to_clean_error(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    with patch("marginal.cli.review.GitHubClient") as mock_client_cls:
        client = mock_client_cls.return_value
        client.get_pull_request.return_value = {
            "title": "Fix flaky retry logic",
            "state": "open",
            "base": {"sha": "abc123"},
            "head": {"sha": "def456"},
        }
        client.get_pull_request_files.return_value = []
        client.create_review.side_effect = PermissionDeniedError(
            "this operation requires permissions.write.comments"
        )

        exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42", "--comment"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "marginal review:" in err
    assert "Traceback" not in err


# -- review: inline comment building -------------------------------------


def test_build_inline_comments_skips_findings_without_a_line():
    findings = [
        Finding(
            file="a.py", line=None, severity=Severity.LOW, confidence=0.9, message="no line here"
        ),
    ]

    assert _build_inline_comments(findings) == []


def test_build_inline_comments_builds_one_entry_per_anchored_finding():
    findings = [
        Finding(file="a.py", line=10, severity=Severity.HIGH, confidence=0.9, message="issue in a"),
        Finding(
            file="b.py",
            line=None,
            severity=Severity.LOW,
            confidence=0.9,
            message="issue in b, unanchored",
        ),
        Finding(
            file="c.py", line=3, severity=Severity.MEDIUM, confidence=0.9, message="issue in c"
        ),
    ]

    assert _build_inline_comments(findings) == [
        {"path": "a.py", "line": 10, "body": "issue in a"},
        {"path": "c.py", "line": 3, "body": "issue in c"},
    ]


# -- review: LLM finding -------------------------------------------------


def _write_reviewer_config(tmp_path):
    config_dir = tmp_path / ".marginal"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "version: 1\nmodels:\n  reviewer:\n    provider: anthropic\n    model: claude-3-5-sonnet\n"
    )


def test_review_without_reviewer_model_skips_generation(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with (
        patch("marginal.cli.review.GitHubClient") as mock_client_cls,
        patch("marginal.cli.review.get_provider") as mock_get_provider,
    ):
        client = mock_client_cls.return_value
        client.get_pull_request.return_value = {
            "title": "Fix flaky retry logic",
            "state": "open",
            "base": {"sha": "abc123"},
            "head": {"sha": "def456"},
        }
        client.get_pull_request_files.return_value = [{"filename": "marginal/retry.py"}]

        exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 0
    mock_get_provider.assert_not_called()
    out = capsys.readouterr().out
    assert "Finding (" not in out


def test_review_with_anchored_finding_posts_it_as_inline_comment(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config(tmp_path)

    with (
        patch("marginal.cli.review.GitHubClient") as mock_client_cls,
        patch("marginal.cli.review.get_provider") as mock_get_provider,
    ):
        client = mock_client_cls.return_value
        client.get_pull_request.return_value = {
            "title": "Fix flaky retry logic",
            "state": "open",
            "base": {"sha": "abc123"},
            "head": {"sha": "def456"},
        }
        client.get_pull_request_files.return_value = [
            {"filename": "marginal/retry.py", "patch": "@@ -1,3 +1,4 @@\n+time.sleep(1)"}
        ]
        provider = mock_get_provider.return_value
        provider.generate_structured = AsyncMock(
            return_value=Finding(
                file="marginal/retry.py",
                line=2,
                severity=Severity.HIGH,
                confidence=0.9,
                message="This introduces a blocking sleep in an async retry loop.",
            )
        )

        exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42", "--comment"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Finding (high): marginal/retry.py:2" in out
    assert "This introduces a blocking sleep in an async retry loop." in out

    call = provider.generate_structured.call_args
    assert call.kwargs["schema"] is Finding
    prompt = call.args[0]
    assert "marginal/retry.py" in prompt
    assert "time.sleep(1)" in prompt

    # The anchored finding stays in the printed summary above for local
    # visibility, but isn't duplicated into the posted review body -- it
    # only rides along as an inline `comments` entry.
    expected_body = "\n".join(
        [
            "PR #42: Fix flaky retry logic",
            "State: open",
            "Base: abc123  Head: def456",
            "Files changed: 1",
            "  marginal/retry.py",
        ]
    )
    client.create_review.assert_called_once_with(
        42,
        expected_body,
        event="COMMENT",
        comments=[
            {
                "path": "marginal/retry.py",
                "line": 2,
                "body": "This introduces a blocking sleep in an async retry loop.",
            }
        ],
    )


def test_review_with_finding_missing_line_falls_back_to_filename(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config(tmp_path)

    with (
        patch("marginal.cli.review.GitHubClient") as mock_client_cls,
        patch("marginal.cli.review.get_provider") as mock_get_provider,
    ):
        client = mock_client_cls.return_value
        client.get_pull_request.return_value = {
            "title": "Fix flaky retry logic",
            "state": "open",
            "base": {"sha": "abc123"},
            "head": {"sha": "def456"},
        }
        client.get_pull_request_files.return_value = [{"filename": "marginal/retry.py"}]
        provider = mock_get_provider.return_value
        provider.generate_structured = AsyncMock(
            return_value=Finding(
                file="marginal/retry.py",
                line=None,
                severity=Severity.MEDIUM,
                confidence=0.9,
                message="Consider adding a backoff cap.",
            )
        )

        exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Finding (medium): marginal/retry.py" in out
    assert "marginal/retry.py:None" not in out


def test_review_with_unanchored_finding_posts_it_in_the_summary_body_not_inline(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config(tmp_path)

    with (
        patch("marginal.cli.review.GitHubClient") as mock_client_cls,
        patch("marginal.cli.review.get_provider") as mock_get_provider,
    ):
        client = mock_client_cls.return_value
        client.get_pull_request.return_value = {
            "title": "Fix flaky retry logic",
            "state": "open",
            "base": {"sha": "abc123"},
            "head": {"sha": "def456"},
        }
        client.get_pull_request_files.return_value = [{"filename": "marginal/retry.py"}]
        provider = mock_get_provider.return_value
        provider.generate_structured = AsyncMock(
            return_value=Finding(
                file="marginal/retry.py",
                line=None,
                severity=Severity.MEDIUM,
                confidence=0.9,
                message="Consider adding a backoff cap.",
            )
        )

        exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42", "--comment"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Finding (medium): marginal/retry.py" in out

    client.create_review.assert_called_once_with(42, out.rstrip("\n"), event="COMMENT", comments=[])


def test_review_drops_a_finding_below_the_confidence_threshold(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config(tmp_path)

    with (
        patch("marginal.cli.review.GitHubClient") as mock_client_cls,
        patch("marginal.cli.review.get_provider") as mock_get_provider,
    ):
        client = mock_client_cls.return_value
        client.get_pull_request.return_value = {
            "title": "Fix flaky retry logic",
            "state": "open",
            "base": {"sha": "abc123"},
            "head": {"sha": "def456"},
        }
        client.get_pull_request_files.return_value = [
            {"filename": "marginal/retry.py", "patch": "@@ -1,3 +1,4 @@\n+time.sleep(1)"}
        ]
        provider = mock_get_provider.return_value
        provider.generate_structured = AsyncMock(
            return_value=Finding(
                file="marginal/retry.py",
                line=2,
                severity=Severity.LOW,
                confidence=0.5,
                message="Might be worth a second look, but not sure.",
            )
        )

        exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42", "--comment"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Finding (" not in out

    # Below the default confidence_threshold (0.85) -- filtered out entirely,
    # same as if no finding had been generated at all.
    client.create_review.assert_called_once_with(42, out.rstrip("\n"), event="COMMENT", comments=[])


def test_review_with_malformed_structured_output_maps_to_clean_message(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config(tmp_path)

    with (
        patch("marginal.cli.review.GitHubClient") as mock_client_cls,
        patch("marginal.cli.review.get_provider") as mock_get_provider,
    ):
        client = mock_client_cls.return_value
        client.get_pull_request.return_value = {
            "title": "Fix flaky retry logic",
            "state": "open",
            "base": {"sha": "abc123"},
            "head": {"sha": "def456"},
        }
        client.get_pull_request_files.return_value = [{"filename": "marginal/retry.py"}]
        provider = mock_get_provider.return_value
        provider.generate_structured = AsyncMock(return_value=object())

        exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "marginal review:" in err
    assert "Traceback" not in err
    client.create_review.assert_not_called()


def test_review_with_reviewer_model_maps_provider_error_to_clean_message(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config(tmp_path)

    with (
        patch("marginal.cli.review.GitHubClient") as mock_client_cls,
        patch("marginal.cli.review.get_provider") as mock_get_provider,
    ):
        client = mock_client_cls.return_value
        client.get_pull_request.return_value = {
            "title": "Fix flaky retry logic",
            "state": "open",
            "base": {"sha": "abc123"},
            "head": {"sha": "def456"},
        }
        client.get_pull_request_files.return_value = [{"filename": "marginal/retry.py"}]
        mock_get_provider.side_effect = MissingCredentialsError(
            "the anthropic provider requires the ANTHROPIC_API_KEY environment variable"
        )

        exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "marginal review:" in err
    assert "Traceback" not in err
    client.create_review.assert_not_called()
