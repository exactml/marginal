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


def test_get_pull_request_files_returns_json_list(monkeypatch):
    monkeypatch.setenv(GITHUB_TOKEN_ENV_VAR, "ghp_secret")
    session = MagicMock()
    session.request.return_value = _response(200, [{"filename": "a.py", "patch": "@@ -1 +1 @@"}])
    client = _client(session=session)

    result = client.get_pull_request_files(1)

    assert result == [{"filename": "a.py", "patch": "@@ -1 +1 @@"}]


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
