"""`ModelProvider` that runs the local Claude Code CLI on the user's own subscription."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator

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
_SYSTEM_PROMPT = "You are a code reviewer. Answer from the prompt alone."


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
        # With ANTHROPIC_API_KEY set, `claude` bills that key instead of the subscription.
        env = {name: value for name, value in os.environ.items() if name != "ANTHROPIC_API_KEY"}
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
            process.kill()
            await process.wait()
            raise ProviderAPIError(self._name, f"no answer within {TIMEOUT_SECONDS}s") from None
        try:
            response = json.loads(stdout)
        except ValueError:
            detail = stderr.decode(errors="replace").strip()
            raise ProviderAPIError(
                self._name, detail or f"exited {process.returncode} without a JSON answer"
            ) from None
        if response.get("is_error"):
            message = str(response.get("result") or response.get("subtype"))
            if "log in" in message.lower() or "login" in message.lower():
                raise MissingCredentialsError(
                    f"the {self._name!r} provider: {message} -- run `claude` and sign in"
                )
            raise ProviderAPIError(self._name, message)
        record_usage(*self._usage(response))
        return response

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
