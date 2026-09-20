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
