import subprocess

import pytest

from marginal.graph import build_symbol_graph, find_out_of_diff_callers


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def _write(repo, relative_path, content):
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_find_out_of_diff_callers_surfaces_a_caller_outside_the_diff(repo):
    _write(repo, "pkg/a.py", "def helper():\n    return 1\n")
    _write(repo, "pkg/b.py", "def use_helper():\n    return helper()\n")
    graph = build_symbol_graph(repo)

    files = [
        {
            "filename": "pkg/a.py",
            "patch": "@@ -1,2 +1,2 @@\n def helper():\n-    return 1\n+    return 2\n",
        }
    ]

    changed = find_out_of_diff_callers(graph, files)

    assert [c.definition.qualified_name for c in changed] == ["pkg.a.helper"]
    assert [(site.file, site.line) for site in changed[0].callers] == [("pkg/b.py", 2)]


def test_find_out_of_diff_callers_excludes_a_caller_thats_also_in_the_diff(repo):
    _write(repo, "pkg/a.py", "def helper():\n    return 1\n")
    _write(repo, "pkg/b.py", "def use_helper():\n    return helper()\n")
    graph = build_symbol_graph(repo)

    files = [
        {
            "filename": "pkg/a.py",
            "patch": "@@ -1,2 +1,2 @@\n def helper():\n-    return 1\n+    return 2\n",
        },
        {
            "filename": "pkg/b.py",
            "patch": (
                "@@ -1,2 +1,2 @@\n"
                " def use_helper():\n"
                "-    return helper()\n"
                "+    return helper() + 1\n"
            ),
        },
    ]

    changed = find_out_of_diff_callers(graph, files)

    helper_entry = next(c for c in changed if c.definition.qualified_name == "pkg.a.helper")
    assert helper_entry.callers == []


def test_find_out_of_diff_callers_skips_unchanged_definitions(repo):
    _write(
        repo,
        "pkg/a.py",
        "def helper():\n    return 1\n\n\ndef untouched():\n    return 2\n",
    )
    graph = build_symbol_graph(repo)

    files = [
        {
            "filename": "pkg/a.py",
            "patch": "@@ -1,2 +1,2 @@\n def helper():\n-    return 1\n+    return 2\n",
        }
    ]

    changed = find_out_of_diff_callers(graph, files)

    assert [c.definition.qualified_name for c in changed] == ["pkg.a.helper"]


def test_find_out_of_diff_callers_handles_a_missing_patch(repo):
    _write(repo, "pkg/a.py", "def helper():\n    return 1\n")
    graph = build_symbol_graph(repo)

    files = [{"filename": "pkg/a.py"}]

    assert find_out_of_diff_callers(graph, files) == []


def test_find_out_of_diff_callers_matches_a_hunk_that_only_partially_overlaps(repo):
    _write(
        repo,
        "pkg/a.py",
        "def helper():\n    return 1\n\n\ndef other():\n    return 2\n",
    )
    graph = build_symbol_graph(repo)

    # Hunk covers lines 2-3 (the tail of `helper` plus a blank line) --
    # only partially overlapping `helper`'s line_start..line_end span.
    files = [
        {
            "filename": "pkg/a.py",
            "patch": "@@ -2,2 +2,2 @@\n     return 1\n \n",
        }
    ]

    changed = find_out_of_diff_callers(graph, files)

    assert [c.definition.qualified_name for c in changed] == ["pkg.a.helper"]


def test_find_out_of_diff_callers_reports_each_touched_definition_once(repo):
    _write(repo, "pkg/a.py", "def helper():\n    return 1\n")
    graph = build_symbol_graph(repo)

    # Two hunks in the same file both overlap `helper`'s span.
    files = [
        {
            "filename": "pkg/a.py",
            "patch": (
                "@@ -1,1 +1,1 @@\n"
                "-def helper():\n"
                "+def helper(x):\n"
                "@@ -2,1 +2,1 @@\n"
                "-    return 1\n"
                "+    return x\n"
            ),
        }
    ]

    changed = find_out_of_diff_callers(graph, files)

    assert len(changed) == 1
