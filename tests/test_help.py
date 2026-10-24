import pytest

from marginal.cli import main


def test_help_subcommand_prints_top_level_usage(capsys):
    exit_code = main(["help"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "usage: marginal" in out
    assert "init" in out
    assert "review" in out


def test_help_init_prints_init_usage(capsys):
    exit_code = main(["help", "init"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "usage: marginal init" in out
    assert "--force" in out


def test_help_review_prints_review_usage(capsys):
    exit_code = main(["help", "review"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "usage: marginal review" in out
    assert "--repo" in out
    assert "--pr" in out


def test_help_unknown_command_exits_nonzero():
    with pytest.raises(SystemExit) as excinfo:
        main(["help", "not-a-command"])

    assert excinfo.value.code == 2


def test_version_flag_prints_the_installed_version(capsys):
    from importlib.metadata import version

    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out == f"marginal {version('marginal-review')}\n"


def test_commands_still_run_when_package_metadata_is_missing(monkeypatch, capsys):
    from importlib.metadata import PackageNotFoundError

    def missing(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr("marginal.cli.version", missing)

    assert main(["help"]) == 0
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "marginal unknown" in capsys.readouterr().out
