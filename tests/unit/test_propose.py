from unittest.mock import patch

import pytest
from conftest import working_tree_file

from marginal.cli import main
from marginal.github.errors import GitHubAPIError
from marginal.oic.domain.schema import Relation
from marginal.oic.services.proposals import ProposedClaim
from marginal.review import Evidence
from marginal.review.knowledge import knowledge_marker
from marginal.review.schema import Knowledge

PATCH = "@@ -1,1 +1,2 @@\n flask\n+requests==2.31.0\n"
FILES = [{"filename": "requirements.txt", "patch": PATCH}]
INSTALLS = ProposedClaim("widgets", Relation.INSTALLS, "requests@2.31.0")
MERGED = {"base": {"sha": "abc"}, "head": {"sha": "def"}, "state": "closed", "merged": True}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".marginal").mkdir()
    (tmp_path / ".marginal" / "config.yaml").write_text("version: 1\n")
    with patch("marginal.cli.propose.GitHubClient") as cls:
        github = cls.return_value
        github.get_file.side_effect = working_tree_file
        github.get_pull_request.return_value = MERGED
        github.get_pull_request_files.return_value = FILES
        github.list_issue_comments.return_value = []
        github.list_review_comments.return_value = []
        github.list_reviews.return_value = []
        github.get_permission.return_value = "write"
        yield github


def _propose(*args):
    return main(["propose", "--repo", "acme/widgets", "--pr", "42", *args])


def _comment(id, body, login="alice"):
    kind = "Bot" if login.endswith("[bot]") else "User"
    return {"id": id, "body": body, "user": {"login": login, "type": kind}}


def _proposal_body(capsys):
    _propose()
    return capsys.readouterr().out.rstrip("\n")


def test_a_merged_pr_posts_one_proposal(client, capsys):
    assert _propose("--comment") == 0

    body = client.create_issue_comment.call_args.args[1]
    assert "Merged. Proposed for the knowledge graph" in body and INSTALLS.id in body
    assert "candidates" in body


def test_an_open_pr_prints_a_preview_and_posts_nothing(client, capsys):
    client.get_pull_request.return_value = {**MERGED, "state": "open", "merged": False}

    assert _propose("--comment") == 0

    assert "When merged, this PR will propose" in capsys.readouterr().out
    client.create_issue_comment.assert_not_called()


def test_a_pr_closed_without_merging_proposes_nothing(client, capsys):
    client.get_pull_request.return_value = {**MERGED, "merged": False}

    _propose("--comment")

    assert "nothing is proposed" in capsys.readouterr().out
    client.create_issue_comment.assert_not_called()


def test_a_rerun_edits_the_proposal_instead_of_posting_a_second(client, capsys):
    body = _proposal_body(capsys)
    client.list_issue_comments.return_value = [_comment(9, body + " old", "github-actions[bot]")]

    _propose("--comment")

    client.create_issue_comment.assert_not_called()
    assert client.update_issue_comment.call_args.args[0] == 9


def test_an_unchanged_proposal_is_not_rewritten(client, capsys):
    body = _proposal_body(capsys)
    client.list_issue_comments.return_value = [_comment(9, body, "github-actions[bot]")]

    _propose("--comment")

    client.create_issue_comment.assert_not_called()
    client.update_issue_comment.assert_not_called()


def test_a_merged_pr_with_no_knowledge_gets_no_comment(client, capsys):
    client.get_pull_request_files.return_value = [
        {"filename": "app.py", "patch": "@@ -1 +1 @@\n+x"}
    ]

    assert _propose("--comment") == 0

    assert "No knowledge found" in capsys.readouterr().out
    client.create_issue_comment.assert_not_called()


def test_a_person_pasting_the_marker_does_not_take_over_the_proposal(client, capsys):
    body = _proposal_body(capsys)
    client.list_issue_comments.return_value = [_comment(3, body + " x", "mallory")]
    client.get_permission.return_value = "read"

    _propose("--comment")

    client.update_issue_comment.assert_not_called()
    client.create_issue_comment.assert_called_once()


def test_a_proposal_posted_with_a_writers_personal_token_is_edited_not_duplicated(client, capsys):
    # Found on a real run: a personal token posts as the person, not a bot.
    body = _proposal_body(capsys)
    client.list_issue_comments.return_value = [_comment(3, body + " old", "maintainer")]

    _propose("--comment")

    client.create_issue_comment.assert_not_called()
    assert client.update_issue_comment.call_args.args[0] == 3


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


def test_a_maintainer_explaining_a_finding_away_is_proposed_as_a_decision(client, capsys):
    finding = {
        "id": 1,
        "path": "requirements.txt",
        "line": 2,
        "body": "🟡 **Medium**\n\nUnpinned.\n\n<!-- marginal:finding:0000000000000000 -->",
        "user": {"login": "github-actions[bot]", "type": "Bot"},
    }
    reply = {
        "id": 2,
        "in_reply_to_id": 1,
        "body": "Intentional: we pin requests because 2.32 broke retries.",
        "user": {"login": "alice", "type": "User"},
    }
    client.list_review_comments.return_value = [finding, reply]

    _propose()

    assert "| decisionAbout | `requirements.txt`" in capsys.readouterr().out


def test_rules_a_marginal_review_found_are_proposed_at_merge(client, capsys):
    review_body = "### 🤖 marginal review\n\n" + knowledge_marker(
        [
            Knowledge(
                kind="rule",
                statement="Requests is pinned to an exact version.",
                about="requirements.txt",
                evidence=Evidence(file="requirements.txt", line=2, quote="requests==2.31.0"),
            )
        ]
    )
    forged = "### 🤖 marginal review\n" + knowledge_marker(
        [
            Knowledge(
                kind="rule",
                statement="Forged.",
                about="requirements.txt",
                evidence=Evidence(file="requirements.txt", line=2, quote="requests==2.31.0"),
            )
        ]
    )
    client.list_reviews.return_value = [
        {"body": review_body, "user": {"login": "github-actions[bot]", "type": "Bot"}},
        # A reader pasting marginal's heading and marker into their own review.
        {"body": forged, "user": {"login": "mallory", "type": "User"}},
    ]
    client.get_permission.side_effect = lambda login: "read" if login == "mallory" else "write"

    _propose()

    out = capsys.readouterr().out
    assert "rule: Requests is pinned to an exact version." in out
    assert "Forged" not in out


def test_a_reply_from_someone_without_write_access_is_not_a_decision(client, capsys):
    finding = {
        "id": 1,
        "path": "requirements.txt",
        "line": 2,
        "body": "🟡 **Medium**\n\nUnpinned.\n\n<!-- marginal:finding:0000000000000000 -->",
        "user": {"login": "github-actions[bot]", "type": "Bot"},
    }
    reply = {
        "id": 2,
        "in_reply_to_id": 1,
        "body": "Intentional: anyone can pin anything.",
        "user": {"login": "drive-by", "type": "User"},
    }
    client.list_review_comments.return_value = [finding, reply]
    client.get_permission.return_value = "read"

    _propose()

    assert "decisionAbout" not in capsys.readouterr().out


def test_only_the_newest_reviews_knowledge_is_proposed(client, capsys):
    def review(statement):
        rule = Knowledge(
            kind="rule",
            statement=statement,
            about="requirements.txt",
            evidence=Evidence(file="requirements.txt", line=2, quote="requests==2.31.0"),
        )
        body = "### 🤖 marginal review\n" + knowledge_marker([rule])
        return {"body": body, "user": {"login": "github-actions[bot]", "type": "Bot"}}

    client.list_reviews.return_value = [
        review("Requests must be pinned."),
        {"body": "### 🤖 marginal review\nnothing new", "user": {"type": "Bot"}},
        review("Requests is pinned to an exact version."),
    ]

    _propose()

    out = capsys.readouterr().out
    assert "Requests is pinned to an exact version." in out
    assert "Requests must be pinned." not in out
