from pathlib import Path

import pytest

from marginal.config import (
    ConfigParseError,
    ConfigValidationError,
    MarginalConfig,
    ReviewTone,
    load_config,
)

FULL_CONFIG = """
version: 1

review:
  enabled: true
  inline_comments: true
  confidence_threshold: 0.85
  max_comments: 8
  tone: concise

context:
  git_history: true
  code_graph: true
  cross_repository: false

ownership:
  codeowners: true
  notify_responsible: false

models:
  planner:
    provider: anthropic
    model: claude-sonnet
  reviewer:
    provider: openai
    model: codex

policies:
  - .marginal/policies/coding.md
  - .marginal/policies/architecture.md
  - .marginal/policies/review.md

permissions:
  read:
    repository: true
    issues: true
    pull_requests: true
  write:
    comments: true
    labels: false
    approve: false
    push: false
    merge: false
"""


def write_config(repo_root: Path, contents: str) -> None:
    marginal_dir = repo_root / ".marginal"
    marginal_dir.mkdir(parents=True, exist_ok=True)
    (marginal_dir / "config.yaml").write_text(contents)


def test_missing_config_returns_defaults(tmp_path):
    config = load_config(tmp_path)

    assert config == MarginalConfig()
    assert config.review.enabled is True
    assert config.review.confidence_threshold == 0.85
    assert config.review.max_comments == 8
    assert config.review.tone == ReviewTone.CONCISE
    assert config.context.cross_repository is False
    assert config.ownership.notify_responsible is False
    assert config.models == {}
    assert config.policies == []
    assert config.permissions.read.repository is True
    assert config.permissions.write.comments is True
    assert config.permissions.write.labels is False
    assert config.permissions.write.approve is False
    assert config.permissions.write.push is False
    assert config.permissions.write.merge is False


def test_empty_config_file_returns_defaults(tmp_path):
    write_config(tmp_path, "")

    assert load_config(tmp_path) == MarginalConfig()


def test_full_example_from_spec_parses(tmp_path):
    write_config(tmp_path, FULL_CONFIG)

    config = load_config(tmp_path)

    assert config.version == 1
    assert config.review.tone == ReviewTone.CONCISE
    assert config.models["planner"].provider == "anthropic"
    assert config.models["planner"].model == "claude-sonnet"
    assert config.models["reviewer"].provider == "openai"
    assert config.policies == [
        ".marginal/policies/coding.md",
        ".marginal/policies/architecture.md",
        ".marginal/policies/review.md",
    ]


def test_partial_config_merges_with_defaults(tmp_path):
    write_config(tmp_path, "review:\n  tone: strict\n")

    config = load_config(tmp_path)

    assert config.review.tone == ReviewTone.STRICT
    assert config.review.enabled is True
    assert config.review.max_comments == 8
    assert config.context == MarginalConfig().context


def test_unsupported_version_is_rejected(tmp_path):
    write_config(tmp_path, "version: 2\n")

    with pytest.raises(ConfigValidationError, match="unsupported config version"):
        load_config(tmp_path)


@pytest.mark.parametrize("threshold", [-0.1, 1.1])
def test_confidence_threshold_out_of_range_is_rejected(tmp_path, threshold):
    write_config(tmp_path, f"review:\n  confidence_threshold: {threshold}\n")

    with pytest.raises(ConfigValidationError):
        load_config(tmp_path)


@pytest.mark.parametrize("max_comments", [0, -1])
def test_non_positive_max_comments_is_rejected(tmp_path, max_comments):
    write_config(tmp_path, f"review:\n  max_comments: {max_comments}\n")

    with pytest.raises(ConfigValidationError):
        load_config(tmp_path)


def test_invalid_tone_is_rejected(tmp_path):
    write_config(tmp_path, "review:\n  tone: sarcastic\n")

    with pytest.raises(ConfigValidationError):
        load_config(tmp_path)


def test_unknown_top_level_key_is_rejected(tmp_path):
    write_config(tmp_path, "reviw:\n  enabled: false\n")

    with pytest.raises(ConfigValidationError):
        load_config(tmp_path)


def test_unknown_nested_key_is_rejected(tmp_path):
    write_config(tmp_path, "review:\n  enable: false\n")

    with pytest.raises(ConfigValidationError):
        load_config(tmp_path)


def test_incomplete_model_spec_is_rejected(tmp_path):
    write_config(tmp_path, "models:\n  planner:\n    provider: anthropic\n")

    with pytest.raises(ConfigValidationError):
        load_config(tmp_path)


def test_malformed_yaml_is_rejected(tmp_path):
    write_config(tmp_path, "review:\n  enabled: [true\n")

    with pytest.raises(ConfigParseError, match="invalid YAML"):
        load_config(tmp_path)


def test_non_mapping_top_level_is_rejected(tmp_path):
    write_config(tmp_path, "- just\n- a\n- list\n")

    with pytest.raises(ConfigParseError, match="expected a YAML mapping"):
        load_config(tmp_path)


def test_default_permissions_follow_least_privilege():
    permissions = MarginalConfig().permissions

    assert permissions.read.repository is True
    assert permissions.read.issues is True
    assert permissions.read.pull_requests is True
    assert permissions.write.comments is True
    assert permissions.write.labels is False
    assert permissions.write.approve is False
    assert permissions.write.push is False
    assert permissions.write.merge is False
