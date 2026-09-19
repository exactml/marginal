import subprocess

import pytest

from marginal.graph import build_symbol_graph


@pytest.fixture
def repo(tmp_path):
    """A `tmp_path` initialized as an empty git repo.

    `build_symbol_graph` lists files via `git ls-files`, so every fixture
    needs a real (if commit-less) repo underneath it -- `git init` alone is
    enough, `--others --exclude-standard` doesn't require any commits.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def _write(repo, relative_path, content):
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_build_symbol_graph_indexes_module_and_class_level_definitions(repo):
    _write(
        repo,
        "pkg/a.py",
        "def helper():\n"
        "    return 1\n"
        "\n"
        "\n"
        "class Widget:\n"
        "    def render(self):\n"
        "        return helper()\n",
    )

    graph = build_symbol_graph(repo)

    assert set(graph.definitions) == {"pkg.a.helper", "pkg.a.Widget", "pkg.a.Widget.render"}
    helper = graph.definitions["pkg.a.helper"]
    assert helper.file == "pkg/a.py"
    assert (helper.line_start, helper.line_end) == (1, 2)


def test_build_symbol_graph_skips_functions_nested_inside_a_function(repo):
    _write(
        repo,
        "pkg/a.py",
        "def outer():\n    def inner():\n        return 1\n    return inner()\n",
    )

    graph = build_symbol_graph(repo)

    assert set(graph.definitions) == {"pkg.a.outer"}


def test_build_symbol_graph_resolves_a_call_to_its_out_of_file_definition(repo):
    _write(
        repo,
        "pkg/a.py",
        "class Widget:\n    def render(self):\n        return 1\n",
    )
    _write(
        repo,
        "pkg/b.py",
        "from pkg.a import Widget\n\n\ndef use_widget():\n    return Widget().render()\n",
    )

    graph = build_symbol_graph(repo)

    render_callers = graph.callers["pkg.a.Widget.render"]
    assert [(site.file, site.line) for site in render_callers] == [("pkg/b.py", 5)]


def test_build_symbol_graph_prefers_the_same_module_definition_when_names_collide(repo):
    _write(repo, "pkg/b.py", "def shared():\n    pass\n")
    _write(
        repo,
        "pkg/c.py",
        "def shared():\n    pass\n\n\ndef caller():\n    return shared()\n",
    )

    graph = build_symbol_graph(repo)

    assert "pkg.c.shared" in graph.callers
    assert "pkg.b.shared" not in graph.callers


def test_build_symbol_graph_leaves_a_globally_ambiguous_call_unresolved(repo):
    _write(repo, "pkg/a.py", "def shared():\n    pass\n")
    _write(repo, "pkg/b.py", "def shared():\n    pass\n")
    _write(
        repo,
        "pkg/c.py",
        "def caller():\n    return shared()\n",
    )

    graph = build_symbol_graph(repo)

    assert graph.callers.get("pkg.a.shared", []) == []
    assert graph.callers.get("pkg.b.shared", []) == []


def test_build_symbol_graph_ignores_gitignored_files(repo):
    (repo / ".gitignore").write_text("ignored/\n")
    _write(repo, "ignored/a.py", "def should_not_appear():\n    pass\n")
    _write(repo, "pkg/a.py", "def should_appear():\n    pass\n")

    graph = build_symbol_graph(repo)

    assert set(graph.definitions) == {"pkg.a.should_appear"}


def test_build_symbol_graph_handles_a_repo_with_no_python_files(repo):
    (repo / "README.md").write_text("hello")

    graph = build_symbol_graph(repo)

    assert graph.definitions == {}
    assert graph.callers == {}
