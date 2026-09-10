from marginal.policy import load_policies


def test_load_policies_returns_empty_list_for_no_paths(tmp_path):
    assert load_policies(tmp_path, []) == []


def test_load_policies_reads_each_file_relative_to_repo_root(tmp_path):
    policies_dir = tmp_path / ".marginal" / "policies"
    policies_dir.mkdir(parents=True)
    (policies_dir / "coding.md").write_text("Use explicit error handling.")
    (policies_dir / "architecture.md").write_text("Handlers must not touch the database directly.")

    policies = load_policies(
        tmp_path,
        [".marginal/policies/coding.md", ".marginal/policies/architecture.md"],
    )

    assert policies == [
        (".marginal/policies/coding.md", "Use explicit error handling."),
        (
            ".marginal/policies/architecture.md",
            "Handlers must not touch the database directly.",
        ),
    ]


def test_load_policies_skips_a_missing_file_and_warns(tmp_path, capsys):
    policies = load_policies(tmp_path, [".marginal/policies/missing.md"])

    assert policies == []
    err = capsys.readouterr().err
    assert "policy file not found" in err
    assert ".marginal/policies/missing.md" in err


def test_load_policies_skips_only_the_missing_file_among_several(tmp_path, capsys):
    policies_dir = tmp_path / ".marginal" / "policies"
    policies_dir.mkdir(parents=True)
    (policies_dir / "coding.md").write_text("Use explicit error handling.")

    policies = load_policies(
        tmp_path,
        [".marginal/policies/coding.md", ".marginal/policies/missing.md"],
    )

    assert policies == [(".marginal/policies/coding.md", "Use explicit error handling.")]
    assert "missing.md" in capsys.readouterr().err
