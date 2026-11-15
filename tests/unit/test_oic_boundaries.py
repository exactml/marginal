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
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


@pytest.mark.parametrize(("directory", "forbidden"), RULES)
def test_import_boundary(directory, forbidden):
    violations = [
        f"{path.relative_to(ROOT)} imports {name}"
        for path in (ROOT / directory).rglob("*.py")
        for name in _imports(path)
        if any(name == f or name.startswith(f + ".") for f in forbidden)
    ]
    assert not violations
