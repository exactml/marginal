import asyncio
import json
import sys

import pytest

from marginal.config.schema import ModelSpec
from marginal.providers.base import reset_usage, usage
from marginal.providers.claude_code import ClaudeCodeProvider
from marginal.providers.errors import (
    MissingCredentialsError,
    ProviderAPIError,
    ProviderResponseError,
)
from marginal.providers.factory import get_provider
from marginal.review.schema import FindingsResponse

_FINDINGS = {
    "findings": [
        {
            "file": "app.py",
            "line": 2,
            "severity": "medium",
            "message": "Divides by zero.",
            "trigger": "ratio(1, 0)",
            "evidence": [{"file": "app.py", "line": 2, "quote": "return a / b"}],
            "assumptions": [],
        }
    ]
}


def _fake_claude(tmp_path, *answers):
    """A `claude` stand-in that logs each call and prints `answers` in turn."""
    (tmp_path / "answers.json").write_text(json.dumps(list(answers)))
    script = tmp_path / "claude"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys, pathlib\n"
        f"here = pathlib.Path({str(tmp_path)!r})\n"
        "calls = here / 'calls.jsonl'\n"
        "n = len(calls.read_text().splitlines()) if calls.exists() else 0\n"
        "with calls.open('a') as log:\n"
        "    log.write(json.dumps({'argv': sys.argv[1:], 'stdin': sys.stdin.read(),\n"
        "        'env': sorted(os.environ)}) + '\\n')\n"
        "print(json.dumps(json.loads((here / 'answers.json').read_text())[n]))\n"
    )
    script.chmod(0o755)
    return str(script)


def _calls(tmp_path):
    return [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]


def _answer(structured=None, **fields):
    usage_ = {"input_tokens": 3, "cache_creation_input_tokens": 1000, "output_tokens": 50}
    return {"is_error": False, "result": "ok", "structured_output": structured, "usage": usage_} | (
        fields
    )


def test_structured_review_runs_isolated_claude_on_the_subscription(tmp_path, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK"):
        monkeypatch.setenv(name, "would-bill-an-account")
    provider = ClaudeCodeProvider("opus", executable=_fake_claude(tmp_path, _answer(_FINDINGS)))
    reset_usage()

    result = asyncio.run(provider.generate_structured("review this", schema=FindingsResponse))

    assert result == FindingsResponse.model_validate(_FINDINGS)
    (call,) = _calls(tmp_path)
    assert call["stdin"] == "review this"
    assert not {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK"} & set(
        call["env"]
    )
    argv = call["argv"]
    assert argv[:1] == ["-p"]
    for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in argv
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--model") + 1] == "opus"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == (
        FindingsResponse.model_json_schema()
    )
    # Cached prompt tokens count as prompt tokens.
    assert usage() == {"input_tokens": 1003, "output_tokens": 50}


def test_an_invalid_answer_is_retried_once_then_fails(tmp_path):
    bad = _answer({"findings": "not a list"})
    provider = ClaudeCodeProvider("opus", executable=_fake_claude(tmp_path, bad, bad))

    with pytest.raises(ProviderResponseError):
        asyncio.run(provider.generate_structured("review this", schema=FindingsResponse))

    assert len(_calls(tmp_path)) == 2


def test_not_signed_in_is_a_missing_credential(tmp_path):
    answer = {"is_error": True, "result": "Not logged in · Please run /login"}
    provider = ClaudeCodeProvider("opus", executable=_fake_claude(tmp_path, answer))

    with pytest.raises(MissingCredentialsError, match="sign in"):
        asyncio.run(provider.generate("hi"))


def test_another_error_answer_is_an_api_error(tmp_path):
    answer = {"is_error": True, "result": "Claude usage limit reached"}
    provider = ClaudeCodeProvider("opus", executable=_fake_claude(tmp_path, answer))

    with pytest.raises(ProviderAPIError, match="usage limit"):
        asyncio.run(provider.generate("hi"))


def test_a_missing_cli_is_a_missing_credential(tmp_path):
    provider = ClaudeCodeProvider("opus", executable=str(tmp_path / "no-such-claude"))

    with pytest.raises(MissingCredentialsError, match="Claude Code CLI"):
        asyncio.run(provider.generate("hi"))


def test_the_factory_resolves_claude_code():
    assert isinstance(
        get_provider(ModelSpec(provider="claude-code", model="opus")), (ClaudeCodeProvider)
    )
