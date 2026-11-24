import asyncio
import json
import os
import sys
from pathlib import Path

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
        "        'env': sorted(os.environ), 'cwd': os.getcwd(),\n"
        "        'memory_off': os.environ.get('CLAUDE_CODE_DISABLE_AUTO_MEMORY')}) + '\\n')\n"
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
    billed = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_FOUNDRY"}
    for name in billed:
        monkeypatch.setenv(name, "would-bill-an-account")
    provider = ClaudeCodeProvider("opus", executable=_fake_claude(tmp_path, _answer(_FINDINGS)))
    reset_usage()

    result = asyncio.run(provider.generate_structured("review this", schema=FindingsResponse))

    assert result == FindingsResponse.model_validate(_FINDINGS)
    (call,) = _calls(tmp_path)
    assert call["stdin"] == "review this"
    assert not billed & set(call["env"])
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


@pytest.mark.parametrize("answer", [None, ["a list"], "text"])
def test_json_that_is_not_an_object_is_an_api_error(tmp_path, answer):
    provider = ClaudeCodeProvider("opus", executable=_fake_claude(tmp_path, answer))

    with pytest.raises(ProviderAPIError, match="JSON object"):
        asyncio.run(provider.generate("hi"))


def test_a_cancelled_review_kills_the_cli(tmp_path):
    script = tmp_path / "claude"
    script.write_text(
        f"#!{sys.executable}\nimport os, time\n"
        f"open({str(tmp_path / 'pid')!r}, 'w').write(str(os.getpid()))\ntime.sleep(60)\n"
    )
    script.chmod(0o755)
    provider = ClaudeCodeProvider("opus", executable=str(script))

    async def cancel_mid_review():
        task = asyncio.create_task(provider.generate("hi"))
        while not (tmp_path / "pid").exists():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_mid_review())

    pid = int((tmp_path / "pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_a_missing_cli_is_a_missing_credential(tmp_path):
    provider = ClaudeCodeProvider("opus", executable=str(tmp_path / "no-such-claude"))

    with pytest.raises(MissingCredentialsError, match="Claude Code CLI"):
        asyncio.run(provider.generate("hi"))


def test_the_factory_resolves_claude_code():
    assert isinstance(
        get_provider(ModelSpec(provider="claude-code", model="opus")), (ClaudeCodeProvider)
    )


def test_the_reviewer_runs_without_auto_memory_in_an_empty_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # a repo whose auto-memory holds the user's notes
    provider = ClaudeCodeProvider("opus", executable=_fake_claude(tmp_path, _answer()))

    asyncio.run(provider.generate("review this"))

    (call,) = _calls(tmp_path)
    assert call["memory_off"] == "1"
    assert call["cwd"] != str(tmp_path)
    assert not os.path.exists(call["cwd"])  # a temporary directory, removed after


def test_only_the_accounts_email_is_removed_not_other_address_shaped_text(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    account = {"emailAddress": "jo.doe@corp.example"}
    (config / ".claude.json").write_text(json.dumps({"oauthAccount": account}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    message = "Ask jo.doe@corp.example; use x@self.weight and git@github.com:o/r."
    finding = dict(_FINDINGS["findings"][0], message=message)
    provider = ClaudeCodeProvider(
        "opus", executable=_fake_claude(tmp_path, _answer({"findings": [finding]}))
    )

    result = asyncio.run(provider.generate_structured("review", schema=FindingsResponse))

    assert result.findings[0].message == (
        "Ask [REDACTED]; use x@self.weight and git@github.com:o/r."
    )


def test_the_signed_in_account_and_machine_are_removed_from_the_answer(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "jo.doe@corp.example", "fullName": "Jo Doe"}})
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    leaked = "Jo Doe at corp.example (jo.doe) works in " + str(Path.home())
    provider = ClaudeCodeProvider("opus", executable=_fake_claude(tmp_path, _answer(result=leaked)))

    answer = asyncio.run(provider.generate("review corp.example's API"))

    assert "Jo Doe" not in answer and "jo.doe" not in answer and str(Path.home()) not in answer
    assert "corp.example" in answer  # named in the prompt, so it stays


def test_account_terms_redact_whole_words_only_and_emails_ignore_case(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    account = {"emailAddress": "anne.lee@corp.example", "fullName": "Ann"}
    (config / ".claude.json").write_text(json.dumps({"oauthAccount": account}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    said = "Annexes and annotations stay; anne.lee leaks; Ops@Shop.example is quoted."
    provider = ClaudeCodeProvider("opus", executable=_fake_claude(tmp_path, _answer(result=said)))

    answer = asyncio.run(provider.generate("mail ops@shop.example"))

    assert answer == "Annexes and annotations stay; [REDACTED] leaks; Ops@Shop.example is quoted."


def test_version_pins_stay_and_name_parts_go(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    account = {"emailAddress": "mark.stone@corp.example", "fullName": "Mark Stone"}
    (config / ".claude.json").write_text(json.dumps({"oauthAccount": account}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    said = "Thanks Mark: upgrade to requests@2.33.0 or @scope/pkg@1.0.0; mark it done."
    provider = ClaudeCodeProvider("opus", executable=_fake_claude(tmp_path, _answer(result=said)))

    answer = asyncio.run(provider.generate("review"))

    assert (
        answer == "Thanks [REDACTED]: upgrade to requests@2.33.0 or @scope/pkg@1.0.0; mark it done."
    )


@pytest.mark.parametrize("account", ["a string", ["a", "list"], None])
def test_an_odd_account_in_the_config_never_breaks_a_review(tmp_path, monkeypatch, account):
    config = tmp_path / "config"
    config.mkdir()
    (config / ".claude.json").write_text(json.dumps({"oauthAccount": account}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    provider = ClaudeCodeProvider("opus", executable=_fake_claude(tmp_path, _answer(result="ok")))
    assert asyncio.run(provider.generate("review")) == "ok"


def test_a_one_word_name_never_redacts_the_ordinary_word(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    account = {"emailAddress": "mark@corp.example", "displayName": "Mark"}
    (config / ".claude.json").write_text(json.dumps({"oauthAccount": account}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    said = "Thanks Mark; use pytest.mark.parametrize and mark it done."
    provider = ClaudeCodeProvider("opus", executable=_fake_claude(tmp_path, _answer(result=said)))

    answer = asyncio.run(provider.generate("review the Markdown"))

    assert answer == "Thanks [REDACTED]; use pytest.mark.parametrize and mark it done."


def test_no_home_directory_never_breaks_a_review(tmp_path, monkeypatch):
    def no_home():
        raise RuntimeError("Could not determine home directory")

    monkeypatch.setattr(Path, "home", no_home)
    provider = ClaudeCodeProvider("opus", executable=_fake_claude(tmp_path, _answer(result="ok")))
    assert asyncio.run(provider.generate("review")) == "ok"


def test_a_split_local_part_and_an_accent_free_name_are_redacted(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    account = {"emailAddress": "renee.dubois@corp.example", "fullName": "Renée Dubois"}
    (config / ".claude.json").write_text(json.dumps({"oauthAccount": account}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    said = "Likely Renee Dubois, or Renée; dubois as a word stays; mark it."
    provider = ClaudeCodeProvider("opus", executable=_fake_claude(tmp_path, _answer(result=said)))

    answer = asyncio.run(provider.generate("review"))

    assert answer == "Likely [REDACTED], or [REDACTED]; dubois as a word stays; mark it."


def test_local_part_words_redact_only_as_names(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "admin.price@corp.example"}})
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    said = "The admin sets a price; ask Price."
    provider = ClaudeCodeProvider("opus", executable=_fake_claude(tmp_path, _answer(result=said)))

    assert asyncio.run(provider.generate("review")) == "The admin sets a price; ask [REDACTED]."
