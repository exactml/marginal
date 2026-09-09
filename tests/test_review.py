import pytest
from pydantic import ValidationError

from marginal.review import Finding, Severity, filter_findings


def _finding(confidence: float, **overrides: object) -> Finding:
    fields: dict[str, object] = {
        "file": "a.py",
        "line": 1,
        "severity": Severity.MEDIUM,
        "message": "an issue",
    }
    fields.update(overrides)
    return Finding(confidence=confidence, **fields)


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_must_be_within_0_and_1(confidence):
    with pytest.raises(ValidationError):
        _finding(confidence)


def test_filter_findings_drops_a_finding_below_the_threshold():
    findings = [_finding(0.5)]

    assert filter_findings(findings, confidence_threshold=0.85, max_comments=8) == []


def test_filter_findings_keeps_a_finding_at_or_above_the_threshold():
    finding = _finding(0.85)

    assert filter_findings([finding], confidence_threshold=0.85, max_comments=8) == [finding]


def test_filter_findings_caps_at_max_comments_highest_confidence_first():
    low = _finding(0.86, file="low.py")
    mid = _finding(0.9, file="mid.py")
    high = _finding(0.99, file="high.py")

    result = filter_findings([low, mid, high], confidence_threshold=0.85, max_comments=2)

    assert result == [high, mid]


def test_filter_findings_drops_low_confidence_before_capping():
    below_threshold = _finding(0.5, file="dropped.py")
    kept = _finding(0.9, file="kept.py")

    result = filter_findings([below_threshold, kept], confidence_threshold=0.85, max_comments=8)

    assert result == [kept]
