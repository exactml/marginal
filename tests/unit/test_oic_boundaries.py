"""The OIC import rules from ADR 0010, checked statically on the source."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "marginal"

PROVIDER_SDKS = ("anthropic", "openai", "claude_agent_sdk")

# (source directory, imports it must never make)
RULES = [
    ("review", ("marginal.oic",)),
    ("graph", ("marginal.oic",)),
    ("oic/domain", (*PROVIDER_SDKS, "marginal.oic.agents", "marginal.oic.store", "sqlalchemy")),
    ("oic/services", (*PROVIDER_SDKS, "marginal.oic.agents")),
]


def _imports(path: Path):
    """Every module `path` imports, with relative and `from X import Y` forms resolved."""
    package = path.relative_to(ROOT.parent).parts[:-1]
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else ()
            module = ".".join((*base, *([node.module] if node.module else [])))
            yield module
            # `from marginal.oic import agents` imports marginal.oic.agents.
            yield from (f"{module}.{alias.name}" for alias in node.names)


def _violations(path: Path, forbidden) -> list[str]:
    return [
        name
        for name in _imports(path)
        if any(name == f or name.startswith(f + ".") for f in forbidden)
    ]


@pytest.mark.parametrize(("directory", "forbidden"), RULES)
def test_import_boundary(directory, forbidden):
    if not (ROOT / directory).is_dir():
        pytest.skip(f"marginal/{directory} doesn't exist yet")
    violations = [
        f"{path.relative_to(ROOT)} imports {name}"
        for path in (ROOT / directory).rglob("*.py")
        for name in _violations(path, forbidden)
    ]
    assert not violations


@pytest.mark.parametrize("directory", ["review", "graph", "oic/domain", "oic/services"])
def test_rule_directories_exist(directory):
    # A renamed or mistyped directory would otherwise make its rule check nothing.
    assert (ROOT / directory).is_dir()


@pytest.mark.parametrize(
    "source",
    [
        "import marginal.oic.agents",
        "from marginal.oic.agents import runner",
        "from marginal.oic import agents",
        "from ..agents import runner",
        "from .. import agents",
    ],
)
def test_every_import_form_is_caught(tmp_path, monkeypatch, source):
    module = tmp_path / "marginal" / "oic" / "domain" / "bad.py"
    module.parent.mkdir(parents=True)
    module.write_text(source + "\n")
    monkeypatch.setattr(f"{__name__}.ROOT", tmp_path / "marginal")
    assert _violations(module, ("marginal.oic.agents",))
