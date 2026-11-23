import base64
from unittest.mock import MagicMock

import pytest

from marginal.config.schema import PermissionsConfig, PermissionsRead, PermissionsWrite
from marginal.github.client import GitHubClient
from marginal.github.credentials import GITHUB_TOKEN_ENV_VAR, require_github_token
from marginal.github.errors import (
    GitHubAPIError,
    GitHubAuthenticationError,
    GitHubNotFoundError,
    PermissionDeniedError,
)


def _response(status_code=200, json_data=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = {} if json_data is None else json_data
    response.text = text
    return response


def _client(permissions=None, session=None):
    return GitHubClient(
        "acme/widgets", permissions or PermissionsConfig(), session=session or MagicMock()
    )


# -- credentials --------------------------------------------------------


def test_require_github_token_returns_value_when_set(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")

    assert require_github_token() == "ghp_secret"


def test_require_github_token_raises_when_missing(monkeypatch):
    monkeypatch.delenv(GITHUB_TOKEN_ENV_VAR, raising=False)

    with pytest.raises(GitHubAuthenticationError, match=GITHUB_TOKEN_ENV_VAR):
        require_github_token()


# -- construction ---------------------------------------------------------


def test_construction_makes_no_network_call_and_needs_no_token(monkeypatch):
    monkeypatch.delenv(GITHUB_TOKEN_ENV_VAR, raising=False)
    session = MagicMock()

    GitHubClient("acme/widgets", PermissionsConfig(), session=session)

    session.request.assert_not_called()


# -- read permission gating ------------------------------------------------


def test_get_pull_request_denied_without_read_permission(monkeypatch):
    monkeypatch.delenv(GITHUB_TOKEN_ENV_VAR, raising=False)
    session = MagicMock()
    client = _client(PermissionsConfig(read=PermissionsRead(pull_requests=False)), session)

    with pytest.raises(PermissionDeniedError, match="permissions.read.pull_requests"):
        client.get_pull_request(1)
    session.request.assert_not_called()


def test_get_pull_request_files_denied_without_read_permission(monkeypatch):
    monkeypatch.delenv(GITHUB_TOKEN_ENV_VAR, raising=False)
    session = MagicMock()
    client = _client(PermissionsConfig(read=PermissionsRead(pull_requests=False)), session)

    with pytest.raises(PermissionDeniedError, match="permissions.read.pull_requests"):
        client.get_pull_request_files(1)
    session.request.assert_not_called()


def test_get_repository_fetches_the_repo(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(200, {"full_name": "acme/widgets"})

    assert _client(session=session).get_repository() == {"full_name": "acme/widgets"}
    args, _ = session.request.call_args
    assert args == ("GET", "https://api.github.com/repos/acme/widgets")


def test_get_repository_denied_without_read_repository(monkeypatch):
    monkeypatch.delenv(GITHUB_TOKEN_ENV_VAR, raising=False)
    session = MagicMock()
    client = _client(PermissionsConfig(read=PermissionsRead(repository=False)), session)

    with pytest.raises(PermissionDeniedError, match="permissions.read.repository"):
        client.get_repository()
    session.request.assert_not_called()


# -- write permission gating -----------------------------------------------


def test_create_review_denied_without_write_comments(monkeypatch):
    monkeypatch.delenv(GITHUB_TOKEN_ENV_VAR, raising=False)
    session = MagicMock()
    client = _client(PermissionsConfig(write=PermissionsWrite(comments=False)), session)

    with pytest.raises(PermissionDeniedError, match="permissions.write.comments"):
        client.create_review(1, "looks good", "COMMENT")
    session.request.assert_not_called()


def test_create_review_approve_denied_without_write_approve(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    permissions = PermissionsConfig(write=PermissionsWrite(comments=True, approve=False))
    client = _client(permissions, session)

    with pytest.raises(PermissionDeniedError, match="permissions.write.approve"):
        client.create_review(1, "ship it", "APPROVE")
    session.request.assert_not_called()


def test_create_review_approve_allowed_with_write_approve(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(200, {"id": 1})
    permissions = PermissionsConfig(write=PermissionsWrite(comments=True, approve=True))
    client = _client(permissions, session)

    result = client.create_review(1, "ship it", "APPROVE")

    assert result == {"id": 1}
    _, kwargs = session.request.call_args
    assert kwargs["json"] == {"body": "ship it", "event": "APPROVE", "comments": []}


# -- auth -------------------------------------------------------------------


def test_get_pull_request_raises_without_token_before_any_request(monkeypatch):
    monkeypatch.delenv(GITHUB_TOKEN_ENV_VAR, raising=False)
    session = MagicMock()
    client = _client(session=session)

    with pytest.raises(GitHubAuthenticationError):
        client.get_pull_request(1)
    session.request.assert_not_called()


def test_missing_token_error_does_not_leak_a_token_value(monkeypatch):
    monkeypatch.delenv(GITHUB_TOKEN_ENV_VAR, raising=False)
    client = _client()

    with pytest.raises(GitHubAuthenticationError) as exc_info:
        client.get_pull_request(1)
    assert "ghp_" not in str(exc_info.value)


def test_unauthorized_response_raises_github_authentication_error(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(401, {"message": "Bad credentials"})
    client = _client(session=session)

    with pytest.raises(GitHubAuthenticationError) as exc_info:
        client.get_pull_request(1)
    assert "ghp_secret" not in str(exc_info.value)


# -- happy-path reads and writes --------------------------------------------


def test_get_pull_request_returns_json_and_sends_bearer_token(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(200, {"number": 1, "title": "Fix bug"})
    client = _client(session=session)

    result = client.get_pull_request(1)

    assert result == {"number": 1, "title": "Fix bug"}
    args, kwargs = session.request.call_args
    assert args[0] == "GET"
    assert args[1] == "https://api.github.com/repos/acme/widgets/pulls/1"
    assert kwargs["headers"]["Authorization"] == "Bearer ghp_secret"


def test_get_file_decodes_a_file_at_a_ref(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    content = base64.b64encode(b"version: 1\n").decode()
    session.request.return_value = _response(200, {"content": content, "encoding": "base64"})
    client = _client(session=session)

    assert client.get_file(".marginal/config.yaml", "abc123") == "version: 1\n"
    args, kwargs = session.request.call_args
    assert args[1] == "https://api.github.com/repos/acme/widgets/contents/.marginal/config.yaml"
    assert kwargs["params"] == {"ref": "abc123"}


@pytest.mark.parametrize(
    "response",
    [_response(404, {"message": "Not Found"}), _response(200, [{"name": "a.md"}])],
)
def test_get_file_is_none_for_a_missing_path_or_a_directory(monkeypatch, response):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = response

    assert _client(session=session).get_file(".marginal/policies", "abc123") is None


def test_list_files_reads_each_subfolder_as_one_tree(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.side_effect = [
        _response(
            200,
            [
                {"type": "file", "path": ".marginal/knowledge/README.md"},
                {"type": "dir", "path": ".marginal/knowledge/paths", "sha": "t1"},
            ],
        ),
        _response(
            200,
            {
                "tree": [
                    {"type": "tree", "path": "shop"},
                    {"type": "blob", "path": "shop/c41d07.yaml"},
                ]
            },
        ),
    ]

    files = _client(session=session).list_files(".marginal/knowledge", "abc123")

    assert files == [".marginal/knowledge/README.md", ".marginal/knowledge/paths/shop/c41d07.yaml"]
    args, kwargs = session.request.call_args
    assert args[1] == "https://api.github.com/repos/acme/widgets/git/trees/t1"
    assert kwargs["params"] == {"recursive": "1"}


def test_get_files_reads_many_files_in_one_graphql_call(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    data = {"repository": {"f0": {"text": "kind: rule\n"}, "f1": None, "f2": {"text": None}}}
    session.request.return_value = _response(200, {"data": data})

    texts = _client(session=session).get_files(["a.yaml", "gone.yaml", "image.png"], "abc123")

    assert texts == {"a.yaml": "kind: rule\n"}
    assert session.request.call_count == 1
    variables = session.request.call_args.kwargs["json"]["variables"]
    assert variables["e0"] == "abc123:a.yaml"
    assert variables["owner"] == "acme"


def test_list_files_warns_when_github_truncates_a_tree(monkeypatch, capsys):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.side_effect = [
        _response(200, [{"type": "dir", "path": "k/paths", "sha": "t1"}]),
        _response(200, {"tree": [{"type": "blob", "path": "a.yaml"}], "truncated": True}),
    ]

    assert _client(session=session).list_files("k", "abc123") == ["k/paths/a.yaml"]
    assert "k/paths has more files than GitHub lists at once" in capsys.readouterr().err


@pytest.mark.parametrize(
    "response",
    [_response(404, {"message": "Not Found"}), _response(200, {"content": "eA=="})],
)
def test_list_files_is_empty_for_a_missing_folder_or_a_file(monkeypatch, response):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = response

    assert _client(session=session).list_files(".marginal/knowledge", "abc123") == []


def test_get_pull_request_files_returns_json_list(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(200, [{"filename": "a.py", "patch": "@@ -1 +1 @@"}])
    client = _client(session=session)

    result = client.get_pull_request_files(1)

    assert result == [{"filename": "a.py", "patch": "@@ -1 +1 @@"}]
    _, kwargs = session.request.call_args
    assert kwargs["params"] == {"per_page": 100, "page": 1}


def test_get_pull_request_files_stops_after_a_single_short_page(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(200, [{"filename": "a.py"}])
    client = _client(session=session)

    client.get_pull_request_files(1)

    session.request.assert_called_once()


def test_get_pull_request_files_follows_every_full_page(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    first_page = [{"filename": f"file_{i}.py"} for i in range(100)]
    second_page = [{"filename": "last.py"}]
    session.request.side_effect = [_response(200, first_page), _response(200, second_page)]
    client = _client(session=session)

    result = client.get_pull_request_files(1)

    assert result == first_page + second_page
    assert session.request.call_count == 2
    first_call, second_call = session.request.call_args_list
    assert first_call.kwargs["params"] == {"per_page": 100, "page": 1}
    assert second_call.kwargs["params"] == {"per_page": 100, "page": 2}


def test_get_compare_files_returns_the_compare_files_list(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    files = [{"filename": "a.py", "status": "modified", "patch": "@@ -1 +1 @@"}]
    session.request.return_value = _response(200, {"status": "ahead", "files": files})

    assert _client(session=session).get_compare_files("abc123", "def456") == files
    args, _ = session.request.call_args
    assert args == ("GET", "https://api.github.com/repos/acme/widgets/compare/abc123...def456")


def test_get_compare_files_denied_without_read_repository(monkeypatch):
    monkeypatch.delenv(GITHUB_TOKEN_ENV_VAR, raising=False)
    session = MagicMock()
    client = _client(PermissionsConfig(read=PermissionsRead(repository=False)), session)

    with pytest.raises(PermissionDeniedError, match="permissions.read.repository"):
        client.get_compare_files("abc123", "def456")
    session.request.assert_not_called()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("list_review_comments", "/repos/acme/widgets/pulls/7/comments"),
        ("list_reviews", "/repos/acme/widgets/pulls/7/reviews"),
        ("list_issue_comments", "/repos/acme/widgets/issues/7/comments"),
    ],
)
def test_pr_comment_reads_follow_every_full_page(monkeypatch, method, path):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    first_page = [{"body": f"comment {i}"} for i in range(100)]
    second_page = [{"body": "last"}]
    session.request.side_effect = [_response(200, first_page), _response(200, second_page)]
    client = _client(session=session)

    result = getattr(client, method)(7)

    assert result == first_page + second_page
    first_call, second_call = session.request.call_args_list
    assert first_call.args == ("GET", f"https://api.github.com{path}")
    assert second_call.kwargs["params"] == {"per_page": 100, "page": 2}


@pytest.mark.parametrize("method", ["list_review_comments", "list_reviews", "list_issue_comments"])
def test_pr_comment_reads_denied_without_read_permission(monkeypatch, method):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    client = _client(PermissionsConfig(read=PermissionsRead(pull_requests=False)), session)

    with pytest.raises(PermissionDeniedError):
        getattr(client, method)(7)
    session.request.assert_not_called()


def test_get_workflow_run_reads_the_run(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(200, {"id": 123, "conclusion": "failure"})
    client = _client(session=session)

    run = client.get_workflow_run(123)

    assert run == {"id": 123, "conclusion": "failure"}
    call = session.request.call_args
    assert call.args == ("GET", "https://api.github.com/repos/acme/widgets/actions/runs/123")


def test_get_workflow_run_denied_without_read_repository(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    client = _client(PermissionsConfig(read=PermissionsRead(repository=False)), session)

    with pytest.raises(PermissionDeniedError, match="permissions.read.repository"):
        client.get_workflow_run(123)
    session.request.assert_not_called()


def test_reply_to_review_comment_posts_in_the_thread(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(201, {"id": 9})
    client = _client(session=session)

    client.reply_to_review_comment(7, 123, "done")

    call = session.request.call_args
    assert call.args == (
        "POST",
        "https://api.github.com/repos/acme/widgets/pulls/7/comments/123/replies",
    )
    assert call.kwargs["json"] == {"body": "done"}


def test_reply_to_review_comment_denied_without_write_comments(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    client = _client(PermissionsConfig(write=PermissionsWrite(comments=False)), session)

    with pytest.raises(PermissionDeniedError):
        client.reply_to_review_comment(7, 123, "done")
    session.request.assert_not_called()


def test_add_labels_posts_them_on_the_issue(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(200, [{"name": "marginal:high"}])
    client = _client(PermissionsConfig(write=PermissionsWrite(labels=True)), session)

    client.add_labels(7, ["marginal:high"])

    call = session.request.call_args
    assert call.args == ("POST", "https://api.github.com/repos/acme/widgets/issues/7/labels")
    assert call.kwargs["json"] == {"labels": ["marginal:high"]}


def test_remove_label_deletes_it_with_the_name_url_encoded(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(200, [])
    client = _client(PermissionsConfig(write=PermissionsWrite(labels=True)), session)

    client.remove_label(7, "marginal:critical")

    call = session.request.call_args
    assert call.args == (
        "DELETE",
        "https://api.github.com/repos/acme/widgets/issues/7/labels/marginal%3Acritical",
    )


def test_remove_label_already_gone_is_not_an_error(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(404, {"message": "Label does not exist"})
    client = _client(PermissionsConfig(write=PermissionsWrite(labels=True)), session)

    client.remove_label(7, "marginal:critical")

    session.request.assert_called_once()


def test_remove_label_denied_without_write_labels(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    client = _client(session=session)

    with pytest.raises(PermissionDeniedError, match="permissions.write.labels"):
        client.remove_label(7, "marginal:critical")
    session.request.assert_not_called()


def test_add_labels_denied_without_write_labels(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    client = _client(session=session)

    with pytest.raises(PermissionDeniedError, match="permissions.write.labels"):
        client.add_labels(7, ["marginal:high"])
    session.request.assert_not_called()


def _threads_page(nodes, next_cursor=None):
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {
                            "hasNextPage": next_cursor is not None,
                            "endCursor": next_cursor,
                        },
                        "nodes": nodes,
                    }
                }
            }
        }
    }


def _thread_node(id, resolved, comment_id):
    return {"id": id, "isResolved": resolved, "comments": {"nodes": [{"databaseId": comment_id}]}}


def test_list_review_threads_follows_every_page_and_maps_first_comment(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.side_effect = [
        _response(200, _threads_page([_thread_node("T1", False, 11)], next_cursor="c1")),
        _response(200, _threads_page([_thread_node("T2", True, 22)])),
    ]
    client = _client(session=session)

    assert client.list_review_threads(7) == [
        {"id": "T1", "is_resolved": False, "comment_id": 11},
        {"id": "T2", "is_resolved": True, "comment_id": 22},
    ]
    first, second = session.request.call_args_list
    assert first.args == ("POST", "https://api.github.com/graphql")
    assert first.kwargs["json"]["variables"] == {
        "owner": "acme",
        "name": "widgets",
        "number": 7,
        "cursor": None,
    }
    assert second.kwargs["json"]["variables"]["cursor"] == "c1"


def test_graphql_errors_raise_even_with_http_200(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(
        200, {"errors": [{"message": "Resource not accessible by integration"}]}
    )
    client = _client(session=session)

    with pytest.raises(GitHubAPIError, match="Resource not accessible by integration"):
        client.resolve_review_thread("T1")


def test_resolve_review_thread_sends_the_mutation(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(200, {"data": {"resolveReviewThread": {}}})
    client = _client(session=session)

    client.resolve_review_thread("T1")

    payload = session.request.call_args.kwargs["json"]
    assert "resolveReviewThread" in payload["query"]
    assert payload["variables"] == {"id": "T1"}


def test_resolve_review_thread_denied_without_write_comments(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    client = _client(PermissionsConfig(write=PermissionsWrite(comments=False)), session)

    with pytest.raises(PermissionDeniedError):
        client.resolve_review_thread("T1")
    session.request.assert_not_called()


# -- API errors ---------------------------------------------------------


def test_not_found_raises_github_not_found_error(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(404, {"message": "Not Found"})
    client = _client(session=session)

    with pytest.raises(GitHubNotFoundError) as exc_info:
        client.get_pull_request(999)
    assert exc_info.value.status_code == 404


def test_server_error_raises_github_api_error_with_status_and_message(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(500, {"message": "Internal Server Error"})
    client = _client(session=session)

    with pytest.raises(GitHubAPIError) as exc_info:
        client.get_pull_request(1)
    assert exc_info.value.status_code == 500
    assert "Internal Server Error" in str(exc_info.value)


def test_issue_comments_are_created_and_updated(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(201, {"id": 5})
    client = _client(session=session)

    client.create_issue_comment(7, "hello")
    created = session.request.call_args
    client.update_issue_comment(5, "edited")
    updated = session.request.call_args

    assert created.args == ("POST", "https://api.github.com/repos/acme/widgets/issues/7/comments")
    assert created.kwargs["json"] == {"body": "hello"}
    assert updated.args == (
        "PATCH",
        "https://api.github.com/repos/acme/widgets/issues/comments/5",
    )
    assert updated.kwargs["json"] == {"body": "edited"}


def test_issue_comment_writes_denied_without_write_comments(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    client = _client(PermissionsConfig(write=PermissionsWrite(comments=False)), session)

    with pytest.raises(PermissionDeniedError):
        client.create_issue_comment(7, "hello")
    with pytest.raises(PermissionDeniedError):
        client.update_issue_comment(5, "edited")
    session.request.assert_not_called()


def test_get_permission_reads_the_collaborator_permission(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(200, {"permission": "write"})
    client = _client(session=session)

    assert client.get_permission("alice") == "write"
    assert session.request.call_args.args == (
        "GET",
        "https://api.github.com/repos/acme/widgets/collaborators/alice/permission",
    )


def test_get_permission_of_an_unknown_user_is_none(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(404, {"message": "Not Found"})

    assert _client(session=session).get_permission("ghost") == "none"


def test_set_branch_creates_a_missing_branch_and_moves_an_existing_one(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.side_effect = [
        _response(404, {"message": "Not Found"}),
        _response(201, {}),
        _response(200, {"object": {"sha": "old"}}),
        _response(200, {}),
    ]
    client = _client(PermissionsConfig(write=PermissionsWrite(push=True)), session)

    client.set_branch("marginal/knowledge", "s1")
    client.set_branch("marginal/knowledge", "s2")

    created, moved = session.request.call_args_list[1], session.request.call_args_list[3]
    assert created.args[0] == "POST"
    assert created.kwargs["json"] == {"ref": "refs/heads/marginal/knowledge", "sha": "s1"}
    assert moved.args[0] == "PATCH"
    assert moved.kwargs["json"] == {"sha": "s2", "force": True}


def test_pushing_writes_need_permissions_write_push(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    client = _client()

    with pytest.raises(PermissionDeniedError, match="permissions.write.push"):
        client.set_branch("b", "s")
    with pytest.raises(PermissionDeniedError, match="permissions.write.push"):
        client.create_file("a.yaml", "x", "b", "m")
    with pytest.raises(PermissionDeniedError, match="permissions.write.push"):
        client.create_pull_request("b", "master", "t", "body")


def test_create_file_commits_base64_text_to_a_branch(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(201, {})
    client = _client(PermissionsConfig(write=PermissionsWrite(push=True)), session)

    client.create_file("k/a.yaml", "kind: rule\n", "marginal/knowledge", "Propose")

    args, kwargs = session.request.call_args
    assert (args[0], args[1]) == (
        "PUT",
        "https://api.github.com/repos/acme/widgets/contents/k/a.yaml",
    )
    assert kwargs["json"]["content"] == base64.b64encode(b"kind: rule\n").decode()
    assert kwargs["json"]["branch"] == "marginal/knowledge"
