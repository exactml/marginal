from unittest.mock import AsyncMock, patch

import pytest

from marginal.cli import main
from marginal.cli.review import (
    _base_lines,
    _build_finding_prompt,
    _build_inline_comments,
    _finding_badge,
    _redacted_filenames,
    _redaction_warning_lines,
)
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


@pytest.fixture
def mock_github_client():
    """Patch `marginal.cli.review.GitHubClient`, yielding the class mock.

    Tests read/write `.return_value` for the client instance `main()` will
    receive, e.g. `mock_github_client.return_value.get_pull_request...`.
    """
    with patch("marginal.cli.review.GitHubClient") as mock_client_cls:
        yield mock_client_cls


@pytest.fixture
def mock_provider():
    """Patch `marginal.cli.review.get_provider`, yielding the function mock."""
    with patch("marginal.cli.review.get_provider") as mock_get_provider:
        yield mock_get_provider


def _pull_request(title="Fix flaky retry logic", state="open"):
    return {"title": title, "state": state, "base": {"sha": "abc123"}, "head": {"sha": "def456"}}


def test_review_prints_pr_summary_and_posts_nothing(
    tmp_path, capsys, monkeypatch, mock_github_client
):
    monkeypatch.chdir(tmp_path)
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = [
        {"filename": "marginal/retry.py"},
        {"filename": "tests/test_retry.py"},
    ]

    exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 0
    args, _ = mock_github_client.call_args
    assert args[0] == "acme/widgets"

    out = capsys.readouterr().out
    assert "### 🤖 marginal review" in out
    assert "**PR #42: Fix flaky retry logic** · open · `abc123` → `def456` · 2 files changed" in out
    assert "- `marginal/retry.py`" in out
    assert "- `tests/test_retry.py`" in out
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
def test_review_prints_clean_message_on_error(
    tmp_path, capsys, monkeypatch, mock_github_client, error
):
    monkeypatch.chdir(tmp_path)
    mock_github_client.return_value.get_pull_request.side_effect = error

    exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "marginal review:" in err
    assert "Traceback" not in err


def test_review_with_comment_flag_posts_the_printed_summary(
    tmp_path, capsys, monkeypatch, mock_github_client
):
    monkeypatch.chdir(tmp_path)
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = [
        {"filename": "marginal/retry.py"},
        {"filename": "tests/test_retry.py"},
    ]

    exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42", "--comment"])

    assert exit_code == 0
    out = capsys.readouterr().out

    client.create_review.assert_called_once_with(42, out.rstrip("\n"), event="COMMENT", comments=[])


def test_review_without_comment_flag_posts_nothing(tmp_path, monkeypatch, mock_github_client):
    monkeypatch.chdir(tmp_path)
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = []

    exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 0
    client.create_review.assert_not_called()


def test_review_with_comment_flag_maps_permission_denied_to_clean_error(
    tmp_path, capsys, monkeypatch, mock_github_client
):
    monkeypatch.chdir(tmp_path)
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
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
        {"path": "a.py", "line": 10, "body": "🟠 **High** · 90% confidence\n\nissue in a"},
        {"path": "c.py", "line": 3, "body": "🟡 **Medium** · 90% confidence\n\nissue in c"},
    ]


# -- review: badge and body template --------------------------------------


def test_finding_badge_includes_severity_and_confidence():
    finding = Finding(file="a.py", line=5, severity=Severity.CRITICAL, confidence=0.92, message="x")

    assert _finding_badge(finding, with_location=False) == "🔴 **Critical** · 92% confidence"


def test_finding_badge_with_location_includes_file_and_line():
    finding = Finding(file="a.py", line=5, severity=Severity.CRITICAL, confidence=0.9, message="x")

    assert (
        _finding_badge(finding, with_location=True) == "🔴 **Critical** · 90% confidence — `a.py:5`"
    )


def test_finding_badge_with_location_omits_the_line_when_absent():
    finding = Finding(file="a.py", line=None, severity=Severity.LOW, confidence=0.9, message="x")

    assert _finding_badge(finding, with_location=True) == "⚪ **Low** · 90% confidence — `a.py`"


def test_base_lines_collapses_the_file_list_behind_details():
    rendered = "\n".join(
        _base_lines(42, _pull_request(), ["marginal/retry.py", "tests/test_retry.py"])
    )

    assert "### 🤖 marginal review" in rendered
    assert (
        "**PR #42: Fix flaky retry logic** · open · `abc123` → `def456` · 2 files changed"
        in rendered
    )
    assert "<details>" in rendered
    assert "<summary>Changed files (2)</summary>" in rendered
    assert "- `marginal/retry.py`" in rendered
    assert "- `tests/test_retry.py`" in rendered


def test_base_lines_skips_the_details_block_with_no_files():
    rendered = "\n".join(_base_lines(42, _pull_request(), []))

    assert "0 files changed" in rendered
    assert "<details>" not in rendered


# -- review: policy prompt folding ----------------------------------------


def test_build_finding_prompt_without_policies_is_unchanged():
    files = [{"filename": "marginal/retry.py", "patch": "@@ -1,3 +1,4 @@\n+time.sleep(1)"}]

    prompt = _build_finding_prompt(files, [])

    assert "policies" not in prompt.lower()
    assert prompt.endswith("--- marginal/retry.py ---\n@@ -1,3 +1,4 @@\n+time.sleep(1)")


def test_build_finding_prompt_folds_policy_content_in():
    files = [{"filename": "marginal/retry.py", "patch": "+time.sleep(1)"}]
    policies = [(".marginal/policies/coding.md", "Never use a blocking sleep in async code.")]

    prompt = _build_finding_prompt(files, policies)

    assert ".marginal/policies/coding.md" in prompt
    assert "Never use a blocking sleep in async code." in prompt
    # The diff still follows the policy content rather than being replaced by it.
    assert "+time.sleep(1)" in prompt
    assert prompt.index("Never use a blocking sleep") < prompt.index("+time.sleep(1)")


# -- review: secret redaction in the finding prompt ------------------------


def test_build_finding_prompt_redacts_a_secret_in_the_patch():
    files = [{"filename": "marginal/config.py", "patch": "+api_key = 'AKIAIOSFODNN7EXAMPLE'"}]

    prompt = _build_finding_prompt(files, [])

    assert "AKIAIOSFODNN7EXAMPLE" not in prompt
    assert prompt.endswith("--- marginal/config.py ---\n+api_key = '[REDACTED]'")


def test_redacted_filenames_returns_only_files_whose_patch_changed():
    files = [
        {"filename": "clean.py", "patch": "+x = 1"},
        {"filename": "marginal/config.py", "patch": "+api_key = 'AKIAIOSFODNN7EXAMPLE'"},
    ]

    assert _redacted_filenames(files) == ["marginal/config.py"]


def test_redaction_warning_lines_empty_when_nothing_redacted():
    assert _redaction_warning_lines([]) == []


def test_redaction_warning_lines_names_every_redacted_file():
    rendered = "\n".join(_redaction_warning_lines(["config.py", "settings.py"]))

    assert "⚠️ **Redacted a likely secret**" in rendered
    assert "`config.py`" in rendered
    assert "`settings.py`" in rendered


# -- review: LLM finding -------------------------------------------------


def _write_reviewer_config(tmp_path):
    config_dir = tmp_path / ".marginal"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "version: 1\nmodels:\n  reviewer:\n    provider: anthropic\n    model: claude-3-5-sonnet\n"
    )


def test_review_without_reviewer_model_skips_generation(
    tmp_path, capsys, monkeypatch, mock_github_client, mock_provider
):
    monkeypatch.chdir(tmp_path)
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = [{"filename": "marginal/retry.py"}]

    exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 0
    mock_provider.assert_not_called()
    out = capsys.readouterr().out
    assert "confidence" not in out


def test_review_with_anchored_finding_posts_it_as_inline_comment(
    tmp_path, capsys, monkeypatch, mock_github_client, mock_provider
):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config(tmp_path)
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = [
        {"filename": "marginal/retry.py", "patch": "@@ -1,3 +1,4 @@\n+time.sleep(1)"}
    ]
    provider = mock_provider.return_value
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
    assert "🟠 **High** · 90% confidence — `marginal/retry.py:2`" in out
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
            "### 🤖 marginal review",
            "",
            "**PR #42: Fix flaky retry logic** · open · `abc123` → `def456` · 1 file changed",
            "",
            "<details>",
            "<summary>Changed files (1)</summary>",
            "",
            "- `marginal/retry.py`",
            "",
            "</details>",
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
                "body": (
                    "🟠 **High** · 90% confidence\n\n"
                    "This introduces a blocking sleep in an async retry loop."
                ),
            }
        ],
    )


def test_review_with_finding_missing_line_falls_back_to_filename(
    tmp_path, capsys, monkeypatch, mock_github_client, mock_provider
):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config(tmp_path)
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = [{"filename": "marginal/retry.py"}]
    provider = mock_provider.return_value
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
    assert "🟡 **Medium** · 90% confidence — `marginal/retry.py`" in out
    assert "marginal/retry.py:None" not in out


def test_review_with_unanchored_finding_posts_it_in_the_summary_body_not_inline(
    tmp_path, capsys, monkeypatch, mock_github_client, mock_provider
):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config(tmp_path)
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = [{"filename": "marginal/retry.py"}]
    provider = mock_provider.return_value
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
    assert "🟡 **Medium** · 90% confidence — `marginal/retry.py`" in out

    client.create_review.assert_called_once_with(42, out.rstrip("\n"), event="COMMENT", comments=[])


def test_review_drops_a_finding_below_the_confidence_threshold(
    tmp_path, capsys, monkeypatch, mock_github_client, mock_provider
):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config(tmp_path)
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = [
        {"filename": "marginal/retry.py", "patch": "@@ -1,3 +1,4 @@\n+time.sleep(1)"}
    ]
    provider = mock_provider.return_value
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
    assert "confidence" not in out

    # Below the default confidence_threshold (0.85) -- filtered out entirely,
    # same as if no finding had been generated at all.
    client.create_review.assert_called_once_with(42, out.rstrip("\n"), event="COMMENT", comments=[])


def test_review_with_malformed_structured_output_maps_to_clean_message(
    tmp_path, capsys, monkeypatch, mock_github_client, mock_provider
):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config(tmp_path)
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = [{"filename": "marginal/retry.py"}]
    provider = mock_provider.return_value
    provider.generate_structured = AsyncMock(return_value=object())

    exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "marginal review:" in err
    assert "Traceback" not in err
    client.create_review.assert_not_called()


def test_review_with_reviewer_model_maps_provider_error_to_clean_message(
    tmp_path, capsys, monkeypatch, mock_github_client, mock_provider
):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config(tmp_path)
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = [{"filename": "marginal/retry.py"}]
    mock_provider.side_effect = MissingCredentialsError(
        "the anthropic provider requires the ANTHROPIC_API_KEY environment variable"
    )

    exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "marginal review:" in err
    assert "Traceback" not in err
    client.create_review.assert_not_called()


def _write_reviewer_config_with_policies(tmp_path, policy_paths):
    config_dir = tmp_path / ".marginal"
    config_dir.mkdir()
    policies_yaml = "\n".join(f"  - {policy_path}" for policy_path in policy_paths)
    (config_dir / "config.yaml").write_text(
        "version: 1\n"
        "models:\n"
        "  reviewer:\n"
        "    provider: anthropic\n"
        "    model: claude-3-5-sonnet\n"
        "policies:\n" + policies_yaml + "\n"
    )


def test_review_folds_a_configured_policy_file_into_the_prompt(
    tmp_path, capsys, monkeypatch, mock_github_client, mock_provider
):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config_with_policies(tmp_path, [".marginal/policies/coding.md"])
    policies_dir = tmp_path / ".marginal" / "policies"
    policies_dir.mkdir()
    (policies_dir / "coding.md").write_text("Never use a blocking sleep in async code.")
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = [
        {"filename": "marginal/retry.py", "patch": "@@ -1,3 +1,4 @@\n+time.sleep(1)"}
    ]
    provider = mock_provider.return_value
    provider.generate_structured = AsyncMock(
        return_value=Finding(
            file="marginal/retry.py",
            line=2,
            severity=Severity.HIGH,
            confidence=0.9,
            message="This introduces a blocking sleep in an async retry loop.",
        )
    )

    exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 0
    prompt = provider.generate_structured.call_args.args[0]
    assert ".marginal/policies/coding.md" in prompt
    assert "Never use a blocking sleep in async code." in prompt


def test_review_with_a_missing_policy_file_does_not_crash(
    tmp_path, capsys, monkeypatch, mock_github_client, mock_provider
):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config_with_policies(tmp_path, [".marginal/policies/missing.md"])
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = [{"filename": "marginal/retry.py"}]
    provider = mock_provider.return_value
    provider.generate_structured = AsyncMock(
        return_value=Finding(
            file="marginal/retry.py",
            line=None,
            severity=Severity.LOW,
            confidence=0.9,
            message="Minor nit.",
        )
    )

    exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 0
    err = capsys.readouterr().err
    assert "policy file not found" in err
    assert ".marginal/policies/missing.md" in err
    prompt = provider.generate_structured.call_args.args[0]
    assert "missing.md" not in prompt


# -- review: secret redaction warning --------------------------------------


def _finding(file="marginal/config.py", confidence=0.5, message="not important"):
    return Finding(
        file=file, line=None, severity=Severity.LOW, confidence=confidence, message=message
    )


def test_review_warns_in_the_summary_when_a_secret_is_redacted(
    tmp_path, capsys, monkeypatch, mock_github_client, mock_provider
):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config(tmp_path)
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = [
        {"filename": "marginal/config.py", "patch": "+api_key = 'AKIAIOSFODNN7EXAMPLE'"}
    ]
    provider = mock_provider.return_value
    provider.generate_structured = AsyncMock(return_value=_finding())

    exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "⚠️ **Redacted a likely secret** in `marginal/config.py`" in out

    prompt = provider.generate_structured.call_args.args[0]
    assert "AKIAIOSFODNN7EXAMPLE" not in prompt


def test_review_with_comment_flag_posts_the_redaction_warning_in_the_body(
    tmp_path, monkeypatch, mock_github_client, mock_provider
):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config(tmp_path)
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = [
        {"filename": "marginal/config.py", "patch": "+api_key = 'AKIAIOSFODNN7EXAMPLE'"}
    ]
    provider = mock_provider.return_value
    provider.generate_structured = AsyncMock(return_value=_finding())

    exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42", "--comment"])

    assert exit_code == 0
    body = client.create_review.call_args.args[1]
    assert "⚠️ **Redacted a likely secret** in `marginal/config.py`" in body


def test_review_omits_the_redaction_warning_when_nothing_is_redacted(
    tmp_path, capsys, monkeypatch, mock_github_client, mock_provider
):
    monkeypatch.chdir(tmp_path)
    _write_reviewer_config(tmp_path)
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = [
        {"filename": "marginal/retry.py", "patch": "@@ -1,3 +1,4 @@\n+time.sleep(1)"}
    ]
    provider = mock_provider.return_value
    provider.generate_structured = AsyncMock(return_value=_finding(file="marginal/retry.py"))

    exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Redacted" not in out


def test_review_without_reviewer_model_does_not_scan_for_secrets(
    tmp_path, capsys, monkeypatch, mock_github_client, mock_provider
):
    monkeypatch.chdir(tmp_path)
    client = mock_github_client.return_value
    client.get_pull_request.return_value = _pull_request()
    client.get_pull_request_files.return_value = [
        {"filename": "marginal/config.py", "patch": "+api_key = 'AKIAIOSFODNN7EXAMPLE'"}
    ]

    exit_code = main(["review", "--repo", "acme/widgets", "--pr", "42"])

    assert exit_code == 0
    mock_provider.assert_not_called()
    out = capsys.readouterr().out
    assert "Redacted" not in out
