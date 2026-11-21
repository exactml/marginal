from unittest.mock import patch

import pytest
from conftest import working_tree_file

from marginal.cli import main
from marginal.github.errors import GitHubAPIError
from marginal.oic.domain.schema import Relation
from marginal.oic.services.proposals import ProposedClaim

PATCH = "@@ -1,1 +1,2 @@\n flask\n+requests==2.31.0\n"
FILES = [{"filename": "requirements.txt", "patch": PATCH}]
INSTALLS = ProposedClaim("widgets", Relation.INSTALLS, "requests@2.31.0")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".marginal").mkdir()
    (tmp_path / ".marginal" / "config.yaml").write_text("version: 1\n")
    with patch("marginal.cli.propose.GitHubClient") as cls:
        github = cls.return_value
        github.get_file.side_effect = working_tree_file
        github.get_pull_request.return_value = {
            "base": {"sha": "abc"},
            "head": {"sha": "def"},
            "state": "open",
        }
        github.get_pull_request_files.return_value = FILES
        github.list_issue_comments.return_value = []
        github.get_permission.return_value = "write"
        yield github


def _propose(*args):
    return main(["propose", "--repo", "acme/widgets", "--pr", "42", *args])


def _comment(id, body, login="alice"):
    kind = "Bot" if login.endswith("[bot]") else "User"
    return {"id": id, "body": body, "user": {"login": login, "type": kind}}


def test_prints_the_proposal_without_posting(client, capsys):
    assert _propose() == 0

    out = capsys.readouterr().out
    assert "This PR would record" in out and INSTALLS.id in out
    client.create_issue_comment.assert_not_called()


def test_first_run_posts_one_comment_and_later_runs_edit_it(client):
    _propose("--comment")
    body = client.create_issue_comment.call_args.args[1]
    client.list_issue_comments.return_value = [_comment(9, body, "github-actions[bot]")]
    client.get_pull_request.return_value = {
        "base": {"sha": "abc"},
        "head": {"sha": "def"},
        "merged": True,
    }

    _propose("--comment")

    client.create_issue_comment.assert_called_once()
    client.update_issue_comment.assert_called_once()
    assert client.update_issue_comment.call_args.args[0] == 9
    assert "accepted" in client.update_issue_comment.call_args.args[1]


def test_an_unchanged_proposal_is_not_rewritten(client, capsys):
    _propose()
    body = capsys.readouterr().out.rstrip("\n")
    client.list_issue_comments.return_value = [_comment(9, body, "github-actions[bot]")]

    _propose("--comment")

    client.create_issue_comment.assert_not_called()
    client.update_issue_comment.assert_not_called()


def test_a_writer_can_drop_a_claim_and_a_reader_cannot(client, capsys):
    client.list_issue_comments.return_value = [
        _comment(1, f"/marginal drop {INSTALLS.id}", "reader"),
    ]
    client.get_permission.side_effect = lambda login: {"reader": "read"}.get(login, "write")

    _propose()
    assert "dropped by" not in capsys.readouterr().out

    client.list_issue_comments.return_value.append(
        _comment(2, f"/marginal drop {INSTALLS.id}", "maintainer")
    )
    _propose()
    assert "dropped by `maintainer`" in capsys.readouterr().out


def test_a_pr_closed_without_merging_is_not_recorded(client, capsys):
    client.get_pull_request.return_value = {
        "base": {"sha": "abc"},
        "head": {"sha": "def"},
        "state": "closed",
    }

    _propose()

    assert "not recorded" in capsys.readouterr().out


def test_github_error_exits_1(client, capsys):
    client.get_pull_request_files.side_effect = GitHubAPIError(500, "boom")

    assert _propose() == 1
    assert "marginal propose:" in capsys.readouterr().err


def test_pyproject_is_read_whole_at_the_head_commit(client, capsys):
    client.get_pull_request_files.return_value = [
        {
            "filename": "pyproject.toml",
            "patch": '@@ -2,1 +2,2 @@\n x = ["a"]\n+y = ["sqlalchemy>=2"]\n',
        }
    ]
    client.get_file.side_effect = lambda path, ref: (
        '[project.optional-dependencies]\nx = ["a"]\ny = ["sqlalchemy>=2"]\n'
        if (path, ref) == ("pyproject.toml", "def")
        else working_tree_file(path, ref)
    )

    _propose()

    assert "| dependsOn | `sqlalchemy`" in capsys.readouterr().out


def test_a_person_pasting_the_marker_does_not_take_over_the_proposal(client, capsys):
    _propose()
    body = capsys.readouterr().out.rstrip("\n")
    client.list_issue_comments.return_value = [_comment(3, body, "mallory")]

    _propose("--comment")

    client.update_issue_comment.assert_not_called()
    client.create_issue_comment.assert_called_once()


def test_a_pr_with_no_relations_gets_no_comment(client, capsys):
    client.get_pull_request_files.return_value = [
        {"filename": "app.py", "patch": "@@ -1 +1 @@\n+x"}
    ]

    assert _propose("--comment") == 0

    assert "No relations found" in capsys.readouterr().out
    client.create_issue_comment.assert_not_called()


def test_a_proposal_that_loses_its_last_claim_is_updated_not_left_stale(client, capsys):
    _propose()
    body = capsys.readouterr().out.rstrip("\n")
    client.list_issue_comments.return_value = [_comment(9, body, "github-actions[bot]")]
    client.get_pull_request_files.return_value = [
        {"filename": "app.py", "patch": "@@ -1 +1 @@\n+x"}
    ]

    _propose("--comment")

    assert "No relations found" in client.update_issue_comment.call_args.args[1]
