"""Review validation, deduplication, and confidence scoring."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from marginal.review.redact import redact_secrets

__all__ = ["Finding", "Severity", "filter_findings", "redact_secrets"]


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
    confidence: float = Field(ge=0.0, le=1.0)
    message: str


def filter_findings(
    findings: list[Finding], *, confidence_threshold: float, max_comments: int
) -> list[Finding]:
    """Drop low-confidence findings, then cap the rest at `max_comments`.

    A finding below `confidence_threshold` is dropped outright. Of the ones
    that pass, only the `max_comments` highest-confidence survive -- so a
    review never posts more than that many findings.
    """
    passing = [finding for finding in findings if finding.confidence >= confidence_threshold]
    return sorted(passing, key=lambda finding: finding.confidence, reverse=True)[:max_comments]
