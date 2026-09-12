import pytest
from pydantic import ValidationError

from marginal.review import Finding, Severity, filter_findings, redact_secrets


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


# -- redact_secrets --------------------------------------------------------


def test_redact_secrets_passes_through_a_patch_with_no_secrets_unchanged():
    patch = "@@ -1,3 +1,4 @@\n import os\n+conn = connect(host='db')\n"

    assert redact_secrets(patch) == patch


def test_redact_secrets_masks_an_aws_access_key():
    assert redact_secrets("+aws_key = AKIAIOSFODNN7EXAMPLE") == "+aws_key = [REDACTED]"


def test_redact_secrets_masks_a_github_token():
    token = "ghp_" + "a" * 36
    assert redact_secrets(f"+token: {token}") == "+token: [REDACTED]"


def test_redact_secrets_masks_a_github_fine_grained_token():
    token = "github_pat_" + "b" * 30
    assert redact_secrets(f"+GITHUB_TOKEN={token}") == "+GITHUB_TOKEN=[REDACTED]"


def test_redact_secrets_masks_a_jwt():
    jwt = (
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    )
    assert redact_secrets(f"+jwt = '{jwt}'") == "+jwt = '[REDACTED]'"


def test_redact_secrets_masks_a_pem_private_key_block():
    patch = (
        "+-----BEGIN RSA PRIVATE KEY-----\n"
        "+MIIEowIBAAKCAQEA1234567890abcdefgh\n"
        "+-----END RSA PRIVATE KEY-----\n"
    )

    assert redact_secrets(patch) == "+[REDACTED]\n"


@pytest.mark.parametrize("assignment", ["api_key", "API_KEY", "token", "secret"])
def test_redact_secrets_masks_a_quoted_generic_assignment(assignment):
    patch = f'+{assignment} = "sk-abcdef1234567890"'

    assert redact_secrets(patch) == f'+{assignment} = "[REDACTED]"'


def test_redact_secrets_masks_an_unquoted_generic_assignment():
    assert redact_secrets("+token: abc123XYZ789") == "+token: [REDACTED]"


def test_redact_secrets_leaves_a_function_call_alone():
    patch = "+token = generate_token()"

    assert redact_secrets(patch) == patch


def test_redact_secrets_leaves_a_plain_lookup_alone():
    patch = '+secret = os.environ["SECRET_KEY"]'

    assert redact_secrets(patch) == patch


def test_redact_secrets_preserves_the_file_separator_framing():
    patch = "+api_key = 'AKIAIOSFODNN7EXAMPLE'"
    prompt = f"--- config.py ---\n{redact_secrets(patch)}"

    assert prompt == "--- config.py ---\n+api_key = '[REDACTED]'"
