"""Review validation, deduplication, and confidence scoring."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class Severity(str, Enum):
    """How serious a finding is."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Finding(BaseModel):
    """One candidate review finding, generated but not yet validated."""

    model_config = ConfigDict(extra="forbid")

    file: str
    line: int | None = None
    severity: Severity
    message: str
