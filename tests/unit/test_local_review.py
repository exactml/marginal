import json
import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from marginal.cli import main
from marginal.config.schema import ModelSpec
from marginal.context.local import LocalCheckout, LocalGitError
from marginal.review.schema import FindingsResponse

_CONFIG = "version: 1\nmodels:\n  reviewer:\n    provider: anthropic\n    model: claude-opus\n"


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    """A repo whose `feature` branch forked from `main` after one commit."""
    _git(tmp_path, "init", "-q", "-b", "main")
    # A local setting that would otherwise widen every patch.
    _git(tmp_path, "config", "diff.context", "100")
    (tmp_path / ".marginal").mkdir()
    (tmp_path / ".marginal" / "config.yaml").write_text(_CONFIG)
    (tmp_path / "app.py").write_text("def ratio(a, b):\n    return a / b if b else 0\n")
    (tmp_path / "old_name.py").write_text("X = 1\n" * 5)
    (tmp_path / "gone.py").write_text("Y = 2\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    return tmp_path


def test_local_files_cover_commits_uncommitted_and_intent_to_add(repo, capsys):
    (repo / "app.py").write_text("def ratio(a, b):\n    return a / b\n")
    _git(repo, "commit", "-q", "-am", "drop the guard")
    _git(repo, "mv", "old_name.py", "new_name.py")
    _git(repo, "rm", "-q", "gone.py")
    (repo / "added.py").write_text("Z = 3\n")
    _git(repo, "add", "-N", "added.py")
    (repo / "scratch.py").write_text("untracked\n")
    checkout = LocalCheckout(str(repo))

    files = checkout.get_compare_files(checkout.merge_base("main"), checkout.head())

    by_name = {f["filename"]: f for f in files}
    assert by_name["app.py"]["status"] == "modified"
    assert by_name["app.py"]["patch"] == (
        "@@ -1,2 +1,2 @@\n def ratio(a, b):\n-    return a / b if b else 0\n+    return a / b"
    )
    assert by_name["added.py"] == {
        "filename": "added.py",
        "status": "added",
        "patch": "@@ -0,0 +1 @@\n+Z = 3",
    }
    assert by_name["gone.py"]["status"] == "removed"
    assert by_name["new_name.py"]["status"] == "renamed"
    assert by_name["new_name.py"]["previous_filename"] == "old_name.py"
    assert "patch" not in by_name["new_name.py"]
    assert "scratch.py" not in by_name
    assert "1 untracked file(s) not reviewed" in capsys.readouterr().err


def test_local_type_change_is_listed_without_a_patch(repo):
    (repo / "link.py").symlink_to("app.py")
    _git(repo, "add", "link.py")
    _git(repo, "commit", "-q", "-m", "add a symlink")
    base = LocalCheckout(str(repo)).head()
    (repo / "link.py").unlink()
    (repo / "link.py").write_text("W = 4\n")
    (repo / "app.py").write_text("def ratio(a, b):\n    return a / b\n")

    files = LocalCheckout(str(repo)).get_compare_files(base, base)

    assert [(f["filename"], f["status"], "patch" in f) for f in files] == [
        ("app.py", "modified", True),
        ("link.py", "modified", False),
    ]


def test_local_get_file_reads_a_commit_not_the_working_tree(repo):
    (repo / ".marginal" / "config.yaml").write_text("version: 1\n")
    checkout = LocalCheckout(str(repo))

    assert checkout.get_file(".marginal/config.yaml", checkout.merge_base("main")) == _CONFIG
    assert checkout.get_file("missing.py", "HEAD") is None


def test_local_merge_base_of_an_unknown_ref_fails_cleanly(repo):
    with pytest.raises(LocalGitError, match="merge-base"):
        LocalCheckout(str(repo)).merge_base("no-such-ref")


def test_review_local_reviews_the_working_tree_without_github(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    (repo / "app.py").write_text("def ratio(a, b):\n    return a / b\n")
    with (
        patch("marginal.cli.review.GitHubClient") as github,
        patch("marginal.cli.review.get_provider") as get_provider,
    ):
        get_provider.return_value.generate_structured = AsyncMock(
            return_value=FindingsResponse(findings=[])
        )

        exit_code = main(
            ["review", "--local", "main", "--provider", "claude-code", "--format", "json"]
        )

    assert exit_code == 0
    github.assert_not_called()
    get_provider.assert_called_once_with(ModelSpec(provider="claude-code", model="claude-opus"))
    prompt = get_provider.return_value.generate_structured.await_args.args[0]
    assert "+    return a / b" in prompt
    result = json.loads(capsys.readouterr().out)
    assert result["repo"] == repo.name
    assert result["changed_files"] == ["app.py"]


def test_review_local_rejects_comment_and_head(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)

    for extra in (["--comment"], ["--head", "abc"]):
        with pytest.raises(SystemExit):
            main(["review", "--local", "main", *extra])

    assert "--head is for --base" in capsys.readouterr().err


def test_review_without_local_still_needs_repo(capsys):
    with pytest.raises(SystemExit):
        main(["review", "--pr", "1"])

    assert "--repo is required, except with --local" in capsys.readouterr().err
