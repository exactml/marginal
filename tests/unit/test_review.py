import pytest

from marginal.review import Finding, Severity, redact_secrets


def _finding(**overrides: object) -> Finding:
    fields: dict[str, object] = {
        "file": "a.py",
        "line": 1,
        "severity": Severity.MEDIUM,
        "message": "an issue",
    }
    fields.update(overrides)
    return Finding(**fields)


def test_every_finding_field_is_required_on_the_wire_and_has_no_default():
    schema = Finding.model_json_schema()

    assert schema["required"] == [
        "file",
        "line",
        "severity",
        "message",
        "trigger",
        "evidence",
        "assumptions",
    ]
    assert not any("default" in prop for prop in schema["properties"].values())
    assert schema["$defs"]["Evidence"]["required"] == ["file", "line", "quote"]
    assert "confidence" not in schema["properties"]


def test_python_callers_can_still_leave_the_evidence_fields_out():
    finding = _finding()

    assert (finding.trigger, finding.evidence, finding.assumptions) == ("", [], [])
    assert finding.checks is None


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "Will undercharge on fractional cents.', 'file'] ,",
            "Will undercharge on fractional cents.",
        ),
        ('Off by one.", "line": 12}', "Off by one."),
        ("Never retried.', 'trigger'] ,", "Never retried."),
        ("The 'file' argument is unused.", "The 'file' argument is unused."),
        ("Wrong key, see 'line'],", "Wrong key, see 'line'],"),
        ("Call `open('a', 'file')` instead.", "Call `open('a', 'file')` instead."),
    ],
)
def test_finding_message_drops_a_leaked_tool_call_fragment(message, expected):
    assert _finding(message=message).message == expected


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


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            '+registry_uri = "https://user:s3cr3tpass@mlflow.acme.io"',
            '+registry_uri = "https://[REDACTED]@mlflow.acme.io"',
        ),
        ("+DB = postgres://app:hunter2@db:5432/shop", "+DB = postgres://[REDACTED]@db:5432/shop"),
    ],
)
def test_redact_secrets_masks_credentials_inside_a_url(line, expected):
    assert redact_secrets(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        '+TRACKING_URI = "local"',
        '+registry.connect("default-profile")',
        '+url = "https://mlflow.acme.io/api"',
        '+url = "https://git@github.com/acme/shop"',
        '+url = "http://localhost:8080/health"',
        '+url = "http://localhost:8080?email=a@b.com"',
    ],
)
def test_redact_secrets_leaves_a_url_without_credentials_alone(line):
    assert redact_secrets(line) == line


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
