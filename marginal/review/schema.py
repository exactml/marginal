"""The finding a model reports, and the checks marginal runs on it."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

__all__ = ["Checks", "Evidence", "Finding", "Severity"]


class Severity(str, Enum):
    """How serious a finding is."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def _every_field_required(schema: dict) -> None:
    """Make every field required on the wire, without a default.

    The model must fill each one (a finding with no trigger or evidence should
    be the model's explicit answer, not an omission), and strict structured
    output doesn't take `default`. Python callers can still leave them out.
    """
    for prop in schema.get("properties", {}).values():
        prop.pop("default", None)
    schema["required"] = list(schema.get("properties", {}))


class Evidence(BaseModel):
    """One line of code a finding rests on, quoted exactly."""

    model_config = ConfigDict(extra="forbid", json_schema_extra=_every_field_required)

    file: str
    line: int
    quote: str


@dataclass(frozen=True)
class Checks:
    """What marginal verified about one finding, with no model call."""

    # One entry per evidence item: whether its quote was found at its line.
    quotes: tuple[bool, ...]
    trigger_concrete: bool
    # A verified quote lies outside the diff's hunks: a caller or nearby code.
    caller_shown: bool

    @property
    def quotes_verified(self) -> int:
        return sum(self.quotes)

    @property
    def quotes_not_found(self) -> int:
        return len(self.quotes) - self.quotes_verified


class Finding(BaseModel):
    """One finding as the model reports it -- what goes wrong, what triggers
    it, the code it rests on, and what it had to assume -- before marginal
    checks it (`marginal.review.evidence`)."""

    model_config = ConfigDict(extra="forbid", json_schema_extra=_every_field_required)

    file: str
    line: int | None = None
    severity: Severity
    message: str
    # The concrete input, state or call path that makes it go wrong.
    trigger: str = ""
    # The lines it rests on, quoted exactly; the prompt asks for 1-3.
    evidence: list[Evidence] = Field(default_factory=list)
    # What must be true that the model couldn't see.
    assumptions: list[str] = Field(default_factory=list)

    # Set by `marginal.review.evidence.decide`; never part of the model's output.
    _checks: Checks | None = PrivateAttr(default=None)

    @property
    def checks(self) -> Checks | None:
        return self._checks

    @field_validator("message")
    @classmethod
    def _strip_leaked_structure(cls, message: str) -> str:
        """Drop a trailing fragment of the tool call itself, which a model can
        write into the string (seen: `...fractional cents.', 'file'] ,`)."""
        return _LEAKED_STRUCTURE.sub("", message) or message


# A closing quote, comma, a quoted field name, then only punctuation that
# closes a list/object to the end. shortcut: matches the shapes seen so far;
# widen it if a leak with a letter after the field name (`'severity': 'high'}`) shows up.
_LEAKED_STRUCTURE = re.compile(
    r"""\s*['"]\s*,\s*['"](?:file|line|severity|message|trigger|evidence|assumptions)['"]?"""
    r"""[^A-Za-z]*[\]}][^A-Za-z]*$"""
)
