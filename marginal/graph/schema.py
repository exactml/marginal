"""The code graph's shape, shared by every language's indexer."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["CallSite", "Definition", "SymbolGraph"]


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
    # Files that couldn't be parsed, and so add no definitions or calls.
    unparsed_files: list[str] = Field(default_factory=list)
