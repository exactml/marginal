from marginal.cli import main
from marginal.config import MarginalConfig, load_config


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
