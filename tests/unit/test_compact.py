from unittest.mock import AsyncMock, patch

import pytest
from conftest import working_tree_file

from marginal.cli import main
from marginal.cli.compact import COMPACT_HEADING
from marginal.github.errors import GitHubAPIError
from marginal.providers.errors import MissingCredentialsError
from marginal.review.dedup import fingerprint_marker
from marginal.review.replies import RESOLVED_MARKER, maintainer_replies
from marginal.review.schema import Recheck, RecheckResponse

PATCH = "@@ -1,2 +1,3 @@\n import time\n+time.sleep(1)\n retry()"
FILES = [{"filename": "retry.py", "patch": PATCH}]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / ".marginal"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "version: 1\nmodels:\n  reviewer:\n    provider: anthropic\n    model: claude-sonnet-5\n"
    )
    with patch("marginal.cli.compact.GitHubClient") as cls:
        cls.return_value.get_file.side_effect = working_tree_file
        cls.return_value.get_pull_request_files.return_value = FILES
        cls.return_value.list_review_comments.return_value = []
        cls.return_value.list_review_threads.return_value = []
        cls.return_value.list_issue_comments.return_value = []
        yield cls.return_value


@pytest.fixture
def provider():
    with patch("marginal.cli.compact.get_provider") as get_provider:
        yield get_provider.return_value


def _finding(id, line=2, path="retry.py", message="time.sleep blocks the event loop."):
    return {
        "id": id,
        "path": path,
        "line": line,
        "body": f"🟠 **High** · 90% confidence\n\n{message}\n\n{fingerprint_marker('0' * 16)}",
        "user": {"login": "github-actions[bot]", "type": "Bot"},
        "created_at": "2026-10-18T10:00:00Z",
    }


def _answers(*results):
    return AsyncMock(
        return_value=RecheckResponse(
            results=[
                Recheck(id=r[0], still_applies=r[1], reason=r[2], dismissed_by=(r + (None,))[3])
                for r in results
            ]
        )
    )


def _person(id, body, login="alice", at="2026-10-18T11:00:00Z", reply_to=None, kind="User"):
    comment = {"id": id, "body": body, "user": {"login": login, "type": kind}, "created_at": at}
    if reply_to is not None:
        comment["in_reply_to_id"] = reply_to
    return comment


def _compact(*args):
    return main(["compact", "--repo", "acme/widgets", "--pr", "42", *args])


def test_no_open_findings_is_a_no_op(client, provider, capsys):
    client.list_review_comments.return_value = [
        {"id": 1, "path": "retry.py", "line": 2, "body": "Can we rename this?"}
    ]

    assert _compact("--comment") == 0

    assert "No open marginal findings on PR #42." in capsys.readouterr().out
    provider.generate_structured.assert_not_called()
    client.reply_to_review_comment.assert_not_called()


def test_a_finding_that_still_applies_stays_open(client, provider, capsys):
    client.list_review_comments.return_value = [_finding(1)]
    provider.generate_structured = _answers((1, True, "Still calls time.sleep."))

    assert _compact("--comment") == 0

    out = capsys.readouterr().out
    assert "✅ 0 resolved · ⏳ 1 still open" in out
    assert "- ⏳ `retry.py:2`: still applies. Still calls time.sleep." in out
    client.reply_to_review_comment.assert_not_called()


def test_a_stale_finding_gets_a_resolution_reply(client, provider, capsys):
    client.list_review_comments.return_value = [_finding(1), _finding(2, line=3)]
    provider.generate_structured = _answers(
        (1, False, "Now uses await asyncio.sleep."), (2, True, "Unchanged.")
    )

    assert _compact("--comment") == 0

    out = capsys.readouterr().out
    assert out.startswith(COMPACT_HEADING)
    assert "re-checked 2 open finding(s) · ✅ 1 resolved · ⏳ 1 still open" in out
    client.reply_to_review_comment.assert_called_once_with(
        42, 1, f"✅ **Resolved**: Now uses await asyncio.sleep.\n\n{RESOLVED_MARKER}"
    )


def test_without_comment_nothing_is_posted(client, provider, capsys):
    client.list_review_comments.return_value = [_finding(1)]
    provider.generate_structured = _answers((1, False, "Fixed."))

    assert _compact() == 0

    assert "- ✅ `retry.py:2`: resolved. Fixed." in capsys.readouterr().out
    client.reply_to_review_comment.assert_not_called()


def test_a_finding_whose_file_left_the_diff_resolves_without_the_model(client, provider):
    client.list_review_comments.return_value = [_finding(1, path="gone.py")]

    assert _compact("--comment") == 0

    provider.generate_structured.assert_not_called()
    body = client.reply_to_review_comment.call_args.args[2]
    assert body.startswith("✅ **Resolved**: its file is no longer changed by this PR")


def test_an_already_resolved_thread_is_skipped(client, provider, capsys):
    client.list_review_comments.return_value = [
        _finding(1),
        {"id": 2, "in_reply_to_id": 1, "body": f"✅ **Resolved**: fixed\n\n{RESOLVED_MARKER}"},
    ]

    assert _compact("--comment") == 0

    assert "No open marginal findings" in capsys.readouterr().out
    provider.generate_structured.assert_not_called()


def test_a_finding_the_model_leaves_out_stays_open(client, provider, capsys):
    client.list_review_comments.return_value = [_finding(1), _finding(2, line=3)]
    # Answers only for 1, plus an id it was never asked about.
    provider.generate_structured = _answers((1, False, "Fixed."), (99, False, "Made up."))

    assert _compact("--comment") == 0

    out = capsys.readouterr().out
    assert "- ⏳ `retry.py:3`: no answer from the model, left open" in out
    assert "✅ 1 resolved" in out
    client.reply_to_review_comment.assert_called_once()


def test_the_prompt_carries_each_finding_once_and_its_file_diff(client, provider):
    client.list_review_comments.return_value = [_finding(7), _finding(8, line=3)]
    provider.generate_structured = _answers((7, True, "x"), (8, True, "y"))

    _compact()

    prompt = provider.generate_structured.call_args.args[0]
    assert "--- finding 7 at retry.py:2 ---" in prompt
    assert "--- finding 8 at retry.py:3 ---" in prompt
    assert prompt.count("--- retry.py ---\n" + PATCH) == 1
    assert "marginal:finding:" not in prompt


def test_compact_without_a_reviewer_model_fails_cleanly(client, provider, tmp_path, capsys):
    (tmp_path / ".marginal" / "config.yaml").write_text("version: 1\n")

    assert _compact() == 1

    assert "needs models.reviewer" in capsys.readouterr().err


def test_compact_over_the_prompt_budget_calls_no_model(client, provider, tmp_path, capsys):
    (tmp_path / ".marginal" / "config.yaml").write_text(
        "version: 1\nreview:\n  max_prompt_tokens: 1\nmodels:\n  reviewer:\n"
        "    provider: anthropic\n    model: claude-sonnet-5\n"
    )
    client.list_review_comments.return_value = [_finding(1)]

    assert _compact("--comment") == 0

    assert "skipped re-checking" in capsys.readouterr().err
    provider.generate_structured.assert_not_called()


def test_compact_missing_credentials_exits_3(client, capsys):
    client.list_review_comments.return_value = [_finding(1)]
    with patch(
        "marginal.cli.compact.get_provider",
        side_effect=MissingCredentialsError("needs ANTHROPIC_API_KEY"),
    ):
        assert _compact() == 3


def test_compact_github_error_exits_1(client, capsys):
    client.list_review_comments.side_effect = GitHubAPIError(500, "Internal Server Error")

    assert _compact() == 1

    assert capsys.readouterr().err.startswith("marginal compact:")


def test_a_resolution_reply_is_not_mistaken_for_a_maintainer_reply():
    comments = [
        _finding(1),
        {
            "id": 2,
            "in_reply_to_id": 1,
            "body": f"✅ **Resolved**: fixed\n\n{RESOLVED_MARKER}",
            "user": {"login": "someone", "type": "User"},
        },
    ]

    assert maintainer_replies(comments) == []


def _thread(comment_id, resolved=False):
    return {"id": f"PRRT_{comment_id}", "is_resolved": resolved, "comment_id": comment_id}


def test_a_stale_finding_has_its_thread_resolved_after_the_reply(client, provider):
    client.list_review_comments.return_value = [_finding(1), _finding(2, line=3)]
    client.list_review_threads.return_value = [_thread(1), _thread(2)]
    provider.generate_structured = _answers((1, False, "Fixed."), (2, True, "Unchanged."))

    assert _compact("--comment") == 0

    client.resolve_review_thread.assert_called_once_with("PRRT_1")
    calls = [c[0] for c in client.method_calls]
    assert calls.index("reply_to_review_comment") < calls.index("resolve_review_thread")


def test_a_failed_thread_resolve_keeps_the_reply_and_the_run(client, provider, capsys):
    client.list_review_comments.return_value = [_finding(1)]
    client.list_review_threads.return_value = [_thread(1)]
    client.resolve_review_thread.side_effect = GitHubAPIError(200, "Resource not accessible")
    provider.generate_structured = _answers((1, False, "Fixed."))

    assert _compact("--comment") == 0

    client.reply_to_review_comment.assert_called_once()
    assert "replied on retry.py:2 but couldn't resolve its thread" in capsys.readouterr().err


def test_a_thread_resolved_by_hand_counts_as_closed(client, provider, capsys):
    client.list_review_comments.return_value = [_finding(1)]
    client.list_review_threads.return_value = [_thread(1, resolved=True)]

    assert _compact("--comment") == 0

    assert "No open marginal findings" in capsys.readouterr().out
    provider.generate_structured.assert_not_called()


def test_without_comment_no_thread_is_resolved(client, provider):
    client.list_review_comments.return_value = [_finding(1)]
    client.list_review_threads.return_value = [_thread(1)]
    provider.generate_structured = _answers((1, False, "Fixed."))

    assert _compact() == 0

    client.resolve_review_thread.assert_not_called()


# -- dismissal by a person's comment ---------------------------------------


def test_a_reply_disputing_the_finding_closes_it_and_credits_the_person(client, provider, capsys):
    client.list_review_comments.return_value = [
        _finding(1),
        _person(5, "This is a false positive: retry runs in a worker thread.", reply_to=1),
    ]
    client.list_review_threads.return_value = [
        {"id": "PRRT_1", "is_resolved": False, "comment_id": 1}
    ]
    provider.generate_structured = _answers((1, True, "Still calls time.sleep.", 5))

    assert _compact("--comment") == 0

    body = client.reply_to_review_comment.call_args.args[2]
    assert body.startswith(
        "✅ **Resolved**: @alice says this isn't an issue (\"This is a false positive: retry "
        'runs in a worker thread."), so marginal is closing it.'
    )
    client.resolve_review_thread.assert_called_once_with("PRRT_1")
    assert "dismissed in comment 5" in capsys.readouterr().out


def test_a_pr_comment_disputing_an_inline_finding_closes_it(client, provider):
    client.list_review_comments.return_value = [_finding(1)]
    client.list_issue_comments.return_value = [
        _person(9, "marginal's note on retry.py's sleep is wrong -- it's intentional.", login="bob")
    ]
    provider.generate_structured = _answers((1, True, "Unchanged.", 9))

    assert _compact("--comment") == 0

    assert "@bob says this isn't an issue" in client.reply_to_review_comment.call_args.args[2]


def test_lgtm_dismisses_nothing(client, provider, capsys):
    client.list_review_comments.return_value = [_finding(1)]
    client.list_issue_comments.return_value = [_person(9, "LGTM")]
    provider.generate_structured = _answers((1, True, "Unchanged.", None))

    assert _compact("--comment") == 0

    client.reply_to_review_comment.assert_not_called()
    assert "⏳ 1 still open" in capsys.readouterr().out


@pytest.mark.parametrize(
    "comment",
    [
        _person(9, "False positive.", login="ci-bot", kind="Bot"),
        _person(9, "False positive.", at="2026-10-18T09:00:00Z"),
    ],
    ids=["from a bot", "before the finding"],
)
def test_a_dismissal_naming_an_ineligible_comment_is_ignored(client, provider, comment):
    client.list_review_comments.return_value = [_finding(1)]
    client.list_issue_comments.return_value = [comment]
    provider.generate_structured = _answers((1, True, "Unchanged.", 9))

    assert _compact("--comment") == 0

    client.reply_to_review_comment.assert_not_called()


def test_a_dismissal_naming_an_unknown_comment_is_ignored(client, provider):
    client.list_review_comments.return_value = [_finding(1)]
    provider.generate_structured = _answers((1, True, "Unchanged.", 12345))

    assert _compact("--comment") == 0

    client.reply_to_review_comment.assert_not_called()


def test_the_prompt_shows_each_findings_replies_and_the_later_pr_comments(client, provider):
    client.list_review_comments.return_value = [
        _finding(1),
        _person(5, "Intentional, see the docstring.", reply_to=1),
        _person(6, "ack", login="github-actions[bot]", kind="Bot", reply_to=1),
    ]
    client.list_issue_comments.return_value = [
        _person(8, "Too early to count.", at="2026-10-18T09:00:00Z"),
        _person(9, "LGTM", login="bob"),
    ]
    provider.generate_structured = _answers((1, True, "Unchanged."))

    _compact()

    prompt = provider.generate_structured.call_args.args[0]
    finding = prompt.index("--- finding 1 at retry.py:2 ---")
    assert prompt.index("reply 5 by @alice: Intentional, see the docstring.") > finding
    assert "Other pull request comments:\n\ncomment 9 by @bob: LGTM" in prompt
    assert "Too early to count." not in prompt
    assert "ack" not in prompt.split("Current diff:")[0]


# -- retrying a thread resolve that failed earlier --------------------------


def _resolution_reply(id, to):
    return {
        "id": id,
        "in_reply_to_id": to,
        "body": f"✅ **Resolved**: fixed\n\n{RESOLVED_MARKER}",
        "user": {"login": "github-actions[bot]", "type": "Bot"},
    }


def test_a_replied_but_unresolved_thread_is_resolved_again(client, provider, capsys):
    """An earlier resolve failed (e.g. no contents: write): the reply exists,
    the thread is still open. The next run resolves it, without a new reply."""
    client.list_review_comments.return_value = [_finding(1), _resolution_reply(2, 1)]
    client.list_review_threads.return_value = [
        {"id": "PRRT_1", "is_resolved": False, "comment_id": 1}
    ]

    assert _compact("--comment") == 0

    client.resolve_review_thread.assert_called_once_with("PRRT_1")
    client.reply_to_review_comment.assert_not_called()
    provider.generate_structured.assert_not_called()


def test_the_retry_skips_threads_already_resolved_and_runs_only_with_comment(client, provider):
    client.list_review_comments.return_value = [_finding(1), _resolution_reply(2, 1)]
    client.list_review_threads.return_value = [
        {"id": "PRRT_1", "is_resolved": True, "comment_id": 1}
    ]
    assert _compact("--comment") == 0
    client.resolve_review_thread.assert_not_called()

    client.list_review_threads.return_value = [
        {"id": "PRRT_1", "is_resolved": False, "comment_id": 1}
    ]
    assert _compact() == 0
    client.resolve_review_thread.assert_not_called()


def test_a_failed_resolve_names_the_missing_permission(client, provider, capsys):
    client.list_review_comments.return_value = [_finding(1), _resolution_reply(2, 1)]
    client.list_review_threads.return_value = [
        {"id": "PRRT_1", "is_resolved": False, "comment_id": 1}
    ]
    client.resolve_review_thread.side_effect = GitHubAPIError(
        200, "Resource not accessible by integration"
    )

    assert _compact("--comment") == 0

    assert "needs `permissions: contents: write`" in capsys.readouterr().err
