"""`ModelProvider` that runs the local Claude Code CLI on the user's own subscription."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import unicodedata
from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import BaseModel

from marginal.providers.base import ModelProvider, record_usage, retry_once_on_validation_error
from marginal.providers.errors import MissingCredentialsError, ProviderAPIError

TIMEOUT_SECONDS = 600
# One isolated answer from the prompt alone: no tools, none of the user's
# settings, memory, MCP servers or skills, and no saved session.
_ISOLATION_FLAGS = (
    "--tools",
    "",
    "--setting-sources",
    "",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--no-session-persistence",
)
# Each of these makes `claude` bill an API key or a cloud account (Bedrock,
# Vertex, Foundry, ...: every `CLAUDE_CODE_USE_*`) instead of the subscription;
# `--setting-sources ""` already keeps a settings `apiKeyHelper` out.
_BILLED_ACCOUNT_ENV = frozenset({"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"})
_BILLED_ACCOUNT_ENV_PREFIX = "CLAUDE_CODE_USE_"
_SYSTEM_PROMPT = "You are a code reviewer. Answer from the prompt alone."
# Claude Code adds the signed-in account's email and the machine's paths to
# every session, and no flag turns that off without dropping subscription
# sign-in. The account's own terms in the answer that aren't in the prompt can
# only come from there, so they're removed before a posted finding carries
# them. Other address-shaped text (`git@github.com`, `x@self.weight`) stays.
# Shorter account terms (a name like `Ann`) are left alone: as whole words
# they'd still redact ordinary text.
_MIN_TERM = 4
_PUBLIC_MAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "yahoo.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "gmx.com",
        "gmx.net",
        "yandex.com",
        "zoho.com",
        "fastmail.com",
    }
)
_MIN_PIECE = 5


class ClaudeCodeProvider(ModelProvider):
    """`ModelProvider` that runs `claude -p`, signed in with the user's Claude
    Code subscription, so no API key is needed. Only for a machine where
    someone has signed in to `claude`, not a CI runner."""

    _name = "claude-code"
    _api_error = OSError

    def __init__(self, model: str, *, base_url: str | None = None, executable: str = "claude"):
        self._model = model
        self._executable = executable

    def _usage(self, response: object) -> tuple[int | None, int | None]:
        usage = response.get("usage") or {}
        if usage.get("input_tokens") is None:
            return None, usage.get("output_tokens")
        # `claude` caches the prompt, and cached tokens are still prompt tokens.
        cached = ("cache_creation_input_tokens", "cache_read_input_tokens")
        input_tokens = usage["input_tokens"] + sum(usage.get(key) or 0 for key in cached)
        return input_tokens, usage.get("output_tokens")

    async def _run(self, prompt: str, *flags: str) -> dict:
        env = {
            name: value
            for name, value in os.environ.items()
            if name not in _BILLED_ACCOUNT_ENV and not name.startswith(_BILLED_ACCOUNT_ENV_PREFIX)
        }
        # Auto-memory is found from the working directory and would put the
        # user's notes about this repo in the prompt; an empty directory and this
        # switch keep both it and the real path out.
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        # Under /tmp, not $TMPDIR, which is often in the user's home.
        base = "/tmp" if os.access("/tmp", os.W_OK) else None
        with tempfile.TemporaryDirectory(dir=base) as empty:
            return await self._run_in(empty, env, prompt, *flags)

    async def _run_in(self, cwd: str, env: dict[str, str], prompt: str, *flags: str) -> dict:
        try:
            process = await asyncio.create_subprocess_exec(
                self._executable,
                "-p",
                *_ISOLATION_FLAGS,
                "--system-prompt",
                _SYSTEM_PROMPT,
                "--model",
                self._model,
                "--output-format",
                "json",
                *flags,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )
        except FileNotFoundError:
            raise MissingCredentialsError(
                f"the {self._name!r} provider needs the Claude Code CLI ({self._executable!r}) "
                "on PATH, signed in"
            ) from None
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(prompt.encode()), TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            raise ProviderAPIError(self._name, f"no answer within {TIMEOUT_SECONDS}s") from None
        finally:
            # Timed out or cancelled: don't leave it running on the user's quota.
            if process.returncode is None:
                process.kill()
                await process.wait()
        try:
            response = json.loads(stdout)
        except ValueError:
            response = None
        if not isinstance(response, dict):
            detail = stderr.decode(errors="replace").strip()
            raise ProviderAPIError(
                self._name, detail or f"exited {process.returncode} without a JSON object"
            )
        if response.get("is_error"):
            # Error text gets the same scrub: it reaches logs and the terminal too.
            message = str(
                _without_injected_emails(response.get("result") or response.get("subtype"), prompt)
            )
            if "log in" in message.lower() or "login" in message.lower():
                raise MissingCredentialsError(
                    f"the {self._name!r} provider: {message} -- run `claude` and sign in"
                )
            raise ProviderAPIError(self._name, message)
        record_usage(*self._usage(response))
        return _without_injected_emails(response, prompt)

    async def generate(self, prompt: str, **kwargs: object) -> str:
        return str((await self._run(prompt)).get("result") or "")

    async def generate_structured(
        self, prompt: str, schema: type[BaseModel], **kwargs: object
    ) -> BaseModel:
        json_schema = json.dumps(schema.model_json_schema())

        async def attempt() -> BaseModel:
            response = await self._run(prompt, "--json-schema", json_schema)
            return schema.model_validate(response.get("structured_output"))

        return await retry_once_on_validation_error(self._name, attempt)

    async def stream(self, prompt: str, **kwargs: object) -> AsyncIterator[str]:
        yield await self.generate(prompt)


def _without_injected_emails(value: object, prompt: str) -> object:
    """`value` (the answer, at any depth) with every term identifying the
    signed-in user or machine that isn't in `prompt` replaced by `[REDACTED]`."""
    whole, parts = _account_terms()
    # Whole words only, so a term never redacts part of another word, and kept
    # only when the prompt has it as a word too (not `Mark` inside `Markdown`).
    # Name parts match in their own case: `Mark` the name, not `mark` the word.
    patterns = [
        _words({t for t in whole if not _words({t}, re.IGNORECASE).search(prompt)}, re.IGNORECASE),
        _words({t for t in parts if not _words({t}, 0).search(prompt)}, 0),
    ]

    def scrub(text: str) -> str:
        for pattern in filter(None, patterns):
            text = pattern.sub("[REDACTED]", text)
        return text

    def walk(item: object) -> object:
        if isinstance(item, str):
            return scrub(item)
        if isinstance(item, dict):
            return {key: walk(inner) for key, inner in item.items()}
        if isinstance(item, list):
            return [walk(inner) for inner in item]
        return item

    return walk(value)


def _words(terms: set[str], flags: int) -> re.Pattern[str] | None:
    if not terms:
        return None
    alternatives = "|".join(map(re.escape, sorted(terms, key=len, reverse=True)))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", flags)


def _account_terms() -> tuple[set[str], set[str]]:
    """What identifies the signed-in user, from Claude Code's config: whole
    terms (the account's email, its local part and domain, its names, and the
    home directory) and name parts (each word of a name).
    Not the bare user name, a one-word name or a plain local part (`will@`):
    as words they can't be told apart from ordinary text."""
    try:
        home = str(Path.home())
    except RuntimeError:  # no HOME and no passwd entry, in some containers
        return set(), set()
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home) / ".claude.json"
    try:
        account = json.loads(config.read_text()).get("oauthAccount")
    except (OSError, ValueError, AttributeError):
        account = None
    account = account if isinstance(account, dict) else {}
    email = str(account.get("emailAddress") or "")
    local, _, domain = email.partition("@")
    stored = [str(account.get(key) or "") for key in ("fullName", "displayName")]
    # A model writes a name capitalized (Jo Doe) whatever the config holds
    # (`jo doe`, `JO DOE`), so that form counts too.
    names = [*stored, *(name.title() for name in stored)]
    distinctive = local if re.search(r"[._\-\d]", local) else ""
    # A public mail provider's domain (gmail.com) identifies nobody.
    own_domain = domain if domain.lower() not in _PUBLIC_MAIL_DOMAINS else ""
    whole = {home, *((email, distinctive, own_domain) if domain else ())}
    # Names match only as written, capitalized: `Will Grant` and `Price` the
    # names, not "will grant" or `price` the words. A distinctive local part is
    # usually a name (`jo.doe`) the model may write out ("Doe"), so its longer
    # words count as names too. The cost: a capitalized ordinary word at the
    # start of a sentence ("Will this crash?" for a Will) is redacted; leaking
    # the name would be worse.
    pieces = {p.capitalize() for p in re.split(r"[._\-\d]+", distinctive) if len(p) >= _MIN_PIECE}
    full = {name for name in names if len(name.split()) > 1}
    parts = {part for name in names for part in re.split(r"[\s._-]+", name)} | pieces | full
    keep = lambda terms: {t for t in terms if len(t) >= _MIN_TERM}  # noqa: E731
    # The model may drop accents (Renée -> Renee): both spellings count.
    plain = lambda terms: terms | {_ascii(t) for t in terms}  # noqa: E731
    return keep(plain(whole)), keep(plain(parts))


def _ascii(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    return "".join(c for c in folded if not unicodedata.combining(c)).replace("ı", "i")
