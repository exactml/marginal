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
    (tmp_path / ".marginal" / "config.yaml").write_text("version: 1\nproposals:\n  enabled: true\n")
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

    assert "| dependsOn | `sqlalchemy>=2`" in capsys.readouterr().out


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


def test_with_proposals_off_it_does_nothing_and_prints_nothing(client, tmp_path, capsys):
    (tmp_path / ".marginal" / "config.yaml").write_text("version: 1\n")

    assert _propose("--comment") == 0

    assert capsys.readouterr() == ("", "")
    client.get_pull_request_files.assert_not_called()
    client.create_issue_comment.assert_not_called()


def test_another_bot_cannot_supply_rules_or_take_over_the_proposal(client, capsys):
    other_bot = {"login": "some-app[bot]", "type": "Bot"}
    forged = "### 🤖 marginal review\n" + knowledge_marker(
        [
            Knowledge(
                kind="rule",
                statement="Forged by another app.",
                about="requirements.txt",
                evidence=Evidence(file="requirements.txt", line=2, quote="requests==2.31.0"),
            )
        ]
    )
    client.list_reviews.return_value = [{"body": forged, "user": other_bot}]
    body = _proposal_body(capsys)
    client.list_issue_comments.return_value = [{"id": 5, "body": body + " x", "user": other_bot}]
    client.get_permission.return_value = "none"

    _propose("--comment")

    assert "Forged" not in client.create_issue_comment.call_args.args[1]
    client.update_issue_comment.assert_not_called()


# -- the rolling knowledge PR ------------------------------------------------


@pytest.fixture
def pushing(client, tmp_path):
    """`client` with `permissions.write.push` on and a maintainer decision to propose."""
    (tmp_path / ".marginal" / "config.yaml").write_text(
        "version: 1\nproposals:\n  enabled: true\npermissions:\n  write:\n    push: true\n"
    )
    client.get_pull_request.return_value = {
        **MERGED,
        "base": {"sha": "abc", "ref": "master", "repo": {"default_branch": "master"}},
        "user": {"login": "bob"},
    }
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
    client.get_file.side_effect = lambda path, ref: None
    client.list_files.return_value = []  # nothing on the knowledge branch yet
    # No knowledge branch yet; the base branch is at `base-head`.
    client.get_branch_sha.side_effect = {"marginal/knowledge": None, "master": "base-head"}.get
    client.list_pull_requests.return_value = []
    client.list_pull_request_commits.return_value = []
    client.create_pull_request.return_value = {"html_url": "https://github.com/acme/widgets/pull/7"}
    return client


def test_a_merged_decision_opens_the_knowledge_pr(pushing):
    assert _propose("--comment") == 0

    pushing.set_branch.assert_called_once_with("marginal/knowledge", "base-head")
    [(path, text, branch, message)] = [c.args for c in pushing.create_file.call_args_list]
    assert path.startswith(".marginal/knowledge/paths/") and path.endswith(".yaml")
    # alice replied with the decision; bob only wrote the PR.
    assert "kind: decision" in text and "pr: 42" in text and "author: alice" in text
    assert (branch, message) == ("marginal/knowledge", f"Propose knowledge from #42: {path}")
    head, base, title, _ = pushing.create_pull_request.call_args.args
    assert (head, base, title) == ("marginal/knowledge", "master", "marginal: knowledge to review")
    comment = pushing.create_issue_comment.call_args.args[1]
    assert "Added to https://github.com/acme/widgets/pull/7 for the team to review." in comment


def test_an_open_knowledge_pr_gets_the_new_files_and_is_not_reopened(pushing):
    pushing.list_pull_requests.return_value = [
        {
            "state": "open",
            "head": {"sha": "k1"},
            "html_url": "https://github.com/acme/widgets/pull/7",
        }
    ]
    pushing.get_branch_sha.side_effect = {"marginal/knowledge": "k1", "master": "base-head"}.get

    _propose("--comment")

    pushing.set_branch.assert_not_called()
    pushing.create_pull_request.assert_not_called()
    assert pushing.create_file.call_count == 1


def _already_on_the_branch(pushing, folder):
    """Make the claim `propose` writes already sit on the branch under `folder`."""
    _propose("--comment")
    written = pushing.create_file.call_args.args[0]
    pushing.reset_mock()
    pushing.list_files.return_value = [f"{folder}/{written.rsplit('/', 1)[-1]}"]


@pytest.mark.parametrize(
    # Where the team left it: where marginal put it, moved to repo-wide, or rejected.
    "folder",
    [".marginal/knowledge/paths", ".marginal/knowledge/repo", ".marginal/knowledge/rejected"],
)
def test_a_claim_already_on_the_knowledge_branch_is_not_written_again(pushing, folder):
    _already_on_the_branch(pushing, folder)

    _propose("--comment")

    pushing.create_file.assert_not_called()


def test_without_push_permission_nothing_is_pushed(pushing, tmp_path):
    (tmp_path / ".marginal" / "config.yaml").write_text("version: 1\nproposals:\n  enabled: true\n")

    _propose("--comment")

    pushing.set_branch.assert_not_called()
    pushing.create_file.assert_not_called()
    assert "Added to" not in pushing.create_issue_comment.call_args.args[1]


def test_only_structural_claims_open_no_knowledge_pr(pushing):
    pushing.list_review_comments.return_value = []

    _propose("--comment")

    pushing.list_pull_requests.assert_not_called()
    pushing.create_file.assert_not_called()


def test_a_failed_push_still_posts_the_proposal(pushing, capsys):
    pushing.create_file.side_effect = GitHubAPIError(403, "Resource not accessible by integration")

    assert _propose("--comment") == 0

    assert "couldn't add to the knowledge PR" in capsys.readouterr().err
    assert "Added to" not in pushing.create_issue_comment.call_args.args[1]


def test_a_missing_base_branch_is_named_and_the_proposal_still_posted(pushing, capsys):
    pushing.get_branch_sha.side_effect = None
    pushing.get_branch_sha.return_value = None

    assert _propose("--comment") == 0

    assert "base branch master not found" in capsys.readouterr().err
    pushing.set_branch.assert_not_called()
    pushing.create_issue_comment.assert_called_once()


def test_after_a_knowledge_pr_is_merged_the_next_one_starts_from_the_base(pushing):
    pushing.list_pull_requests.return_value = [
        {"number": 7, "state": "closed", "merged_at": "2026-11-20", "head": {"sha": "k1"}}
    ]
    pushing.get_branch_sha.side_effect = {"marginal/knowledge": "k1", "master": "base-head"}.get

    _propose("--comment")

    pushing.set_branch.assert_called_once_with("marginal/knowledge", "base-head")
    pushing.create_pull_request.assert_called_once()


def test_files_no_pr_carried_yet_are_kept_and_get_their_pr(pushing):
    """Opening the PR failed last time (e.g. Actions may not create PRs):
    the branch moved past every PR, so its files aren't thrown away."""
    pushing.list_pull_requests.return_value = [{"state": "closed", "head": {"sha": "k1"}}]
    pushing.get_branch_sha.side_effect = {"marginal/knowledge": "k2", "master": "base-head"}.get

    _propose("--comment")

    pushing.set_branch.assert_not_called()
    pushing.create_file.assert_called_once()
    pushing.create_pull_request.assert_called_once()


def test_a_pr_merged_into_another_branch_adds_nothing_to_the_knowledge_pr(pushing):
    pushing.get_pull_request.return_value = {
        **pushing.get_pull_request.return_value,
        "base": {"sha": "abc", "ref": "release/1.x", "repo": {"default_branch": "master"}},
    }

    _propose("--comment")

    pushing.set_branch.assert_not_called()
    pushing.create_file.assert_not_called()
    assert "Added to" not in pushing.create_issue_comment.call_args.args[1]


def test_claims_all_accepted_already_open_no_empty_knowledge_pr(pushing):
    _already_on_the_branch(pushing, ".marginal/knowledge/paths")

    _propose("--comment")

    pushing.set_branch.assert_called_once()
    pushing.create_file.assert_not_called()
    pushing.create_pull_request.assert_not_called()
    assert "Added to" not in pushing.create_issue_comment.call_args.args[1]


# -- rejections ----------------------------------------------------------------

DELETED = ".marginal/knowledge/paths/shop/7be210.yaml"
KEPT = ".marginal/knowledge/paths/shop/a3f91c.yaml"
RECORD = ".marginal/knowledge/rejected/c41d07.yaml"


def _previous_pr(pushing, merged, on_base):
    """Knowledge PR #7, now merged or closed, whose commits added the files
    `DELETED`, `KEPT` and `RECORD`; `on_base` is what reached the base branch."""
    pushing.list_pull_requests.return_value = [
        {
            "number": 7,
            "state": "closed",
            "merged_at": "2026-11-20" if merged else None,
            "head": {"sha": "k3"},
        }
    ]
    pushing.get_branch_sha.side_effect = {"marginal/knowledge": "k3", "master": "base-head"}.get
    pushing.list_pull_request_commits.return_value = [
        {"sha": "k1", "commit": {"message": f"Propose knowledge from #40: {DELETED}"}},
        {"sha": "k2", "commit": {"message": f"Propose knowledge from #41: {KEPT}"}},
        {"sha": "k3", "commit": {"message": f"Record knowledge rejected in #5: {RECORD}"}},
        {"sha": "k4", "commit": {"message": "Delete 7be210.yaml"}},
    ]
    pushing.list_files.side_effect = lambda folder, ref: on_base if ref == "base-head" else []
    pushing.get_file.side_effect = lambda path, ref: (
        f"statement: from {path} at {ref}\n" if path.startswith(".marginal/knowledge/") else None
    )


def _recorded(pushing):
    return {
        c.args[0]: (c.args[1], c.args[3])
        for c in pushing.create_file.call_args_list
        if c.args[0].startswith(".marginal/knowledge/rejected/")
    }


def test_a_claim_the_team_deleted_is_recorded_as_rejected(pushing):
    """The team deleted 7be210 and un-rejected c41d07 before merging #7."""
    _previous_pr(pushing, merged=True, on_base=[KEPT])

    _propose("--comment")

    assert _recorded(pushing) == {
        ".marginal/knowledge/rejected/7be210.yaml": (
            f"statement: from {DELETED} at k1\n",
            "Record knowledge rejected in #7: .marginal/knowledge/rejected/7be210.yaml",
        )
    }
    # Recorded on the fresh branch, before the new claim.
    pushing.set_branch.assert_called_once_with("marginal/knowledge", "base-head")
    assert pushing.create_file.call_args_list[0].args[0].endswith("rejected/7be210.yaml")


def test_closing_a_knowledge_pr_rejects_its_claims_and_keeps_its_records(pushing):
    _previous_pr(pushing, merged=False, on_base=[])

    _propose("--comment")

    assert set(_recorded(pushing)) == {
        ".marginal/knowledge/rejected/7be210.yaml",
        ".marginal/knowledge/rejected/a3f91c.yaml",
        ".marginal/knowledge/rejected/c41d07.yaml",
    }


def test_a_rejection_already_recorded_on_the_base_is_not_written_again(pushing):
    _previous_pr(pushing, merged=True, on_base=[KEPT, ".marginal/knowledge/rejected/7be210.yaml"])

    _propose("--comment")

    assert _recorded(pushing) == {}


def test_a_knowledge_pr_past_githubs_commit_listing_cap_warns(pushing, capsys):
    _previous_pr(pushing, merged=True, on_base=[KEPT])
    commits = pushing.list_pull_request_commits.return_value
    pushing.list_pull_request_commits.return_value = commits + [
        {"sha": f"x{i}", "commit": {"message": "Edit"}} for i in range(250 - len(commits))
    ]

    _propose("--comment")

    assert "knowledge PR #7 has 250 or more commits" in capsys.readouterr().err
    # What the listing shows is still recorded.
    assert ".marginal/knowledge/rejected/7be210.yaml" in _recorded(pushing)
