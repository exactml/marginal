"""Python symbol graph: function/class definitions and their call sites."""

from __future__ import annotations

import ast
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["CallSite", "Definition", "SymbolGraph", "build_symbol_graph"]


class Definition(BaseModel):
    """One function or class definition found while indexing the repo."""

    model_config = ConfigDict(extra="forbid")

    qualified_name: str
    file: str
    line_start: int
    line_end: int


class CallSite(BaseModel):
    """One call expression that resolved to a `Definition`."""

    model_config = ConfigDict(extra="forbid")

    file: str
    line: int


class SymbolGraph(BaseModel):
    """Every indexed definition, plus the call sites that resolve to each.

    `callers` is keyed by the callee's `qualified_name` (see `Definition`)
    and only ever contains resolvable calls -- an ambiguous or dynamic call
    site is dropped rather than guessed, so a missing entry means "no call
    site resolved to this definition", not "this definition is unused".
    """

    model_config = ConfigDict(extra="forbid")

    definitions: dict[str, Definition] = Field(default_factory=dict)
    callers: dict[str, list[CallSite]] = Field(default_factory=dict)


@dataclass
class _RawDefinition:
    qualified_name: str
    simple_name: str
    file: str
    line_start: int
    line_end: int


@dataclass
class _RawCall:
    file: str
    line: int
    name: str


@dataclass
class _FileSymbols:
    definitions: list[_RawDefinition] = field(default_factory=list)
    calls: list[_RawCall] = field(default_factory=list)


def build_symbol_graph(repo_root: Path | str) -> SymbolGraph:
    """Parse every `*.py` file under `repo_root` into a `SymbolGraph`.

    `repo_root` must be a git working tree (or its root) -- the file list
    comes from `git ls-files`, which already resolves `.gitignore` and
    tracked/untracked status correctly, rather than reimplementing that
    logic here.

    Only module-level and class-level (method) definitions are indexed;
    functions nested inside another function are not, though calls made
    from inside them still count towards a caller list.

    A call resolves to a definition on a best-effort basis, in order: a
    same-module function with that name, otherwise the one definition
    anywhere in the repo whose name matches uniquely. A call that matches
    zero or several definitions is left unresolved -- no type inference,
    no guessing.
    """
    root = Path(repo_root)
    files = _list_python_files(root)

    by_qualified: dict[str, Definition] = {}
    by_simple: dict[str, list[Definition]] = defaultdict(list)
    raw_calls: list[_RawCall] = []

    for file in files:
        symbols = _parse_file(root, file)
        raw_calls.extend(symbols.calls)
        for raw in symbols.definitions:
            definition = Definition(
                qualified_name=raw.qualified_name,
                file=raw.file,
                line_start=raw.line_start,
                line_end=raw.line_end,
            )
            by_qualified[raw.qualified_name] = definition
            by_simple[raw.simple_name].append(definition)

    callers: dict[str, list[CallSite]] = defaultdict(list)
    for call in raw_calls:
        target = _resolve_call(call, by_qualified, by_simple)
        if target is not None:
            callers[target.qualified_name].append(CallSite(file=call.file, line=call.line))

    return SymbolGraph(definitions=by_qualified, callers=dict(callers))


def _list_python_files(root: Path) -> list[str]:
    """Every `*.py` file under `root`, respecting `.gitignore`."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.py"],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
    )
    return [path for path in result.stdout.split("\0") if path]


def _parse_file(root: Path, file: str) -> _FileSymbols:
    source = (root / file).read_text()
    tree = ast.parse(source, filename=file)
    visitor = _DefinitionVisitor(file, _module_name(file))
    visitor.visit(tree)
    return _FileSymbols(definitions=visitor.definitions, calls=visitor.calls)


def _module_name(file: str) -> str:
    parts = list(Path(file).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


class _DefinitionVisitor(ast.NodeVisitor):
    """Collects top-level/class-level definitions and every call site.

    `_function_depth` tracks nesting inside function bodies: a def/class
    seen at depth 0 is module- or class-level and gets indexed; anything
    found deeper (a helper nested inside a function) is skipped, since
    it's private to that function and not something another file could
    plausibly call.
    """

    def __init__(self, file: str, module_name: str) -> None:
        self.file = file
        self.definitions: list[_RawDefinition] = []
        self.calls: list[_RawCall] = []
        self._scope: list[str] = [module_name] if module_name else []
        self._function_depth = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if self._function_depth == 0:
            self._record_definition(node)
            self._scope.append(node.name)
            self.generic_visit(node)
            self._scope.pop()
        else:
            self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name is not None:
            self.calls.append(_RawCall(file=self.file, line=node.lineno, name=name))
        self.generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self._function_depth == 0:
            self._record_definition(node)
        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1

    def _record_definition(
        self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        qualified_name = ".".join([*self._scope, node.name])
        self.definitions.append(
            _RawDefinition(
                qualified_name=qualified_name,
                simple_name=node.name,
                file=self.file,
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno) or node.lineno,
            )
        )


def _resolve_call(
    call: _RawCall,
    by_qualified: dict[str, Definition],
    by_simple: dict[str, list[Definition]],
) -> Definition | None:
    same_module_guess = f"{_module_name(call.file)}.{call.name}"
    if same_module_guess in by_qualified:
        return by_qualified[same_module_guess]

    candidates = by_simple.get(call.name, [])
    if len(candidates) == 1:
        return candidates[0]
    return None
