"""Redact likely secrets from diff text before it reaches a model provider."""

from __future__ import annotations

import re

_REDACTED = "[REDACTED]"

_PEM_BLOCK = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)

_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")

_GITHUB_TOKEN = re.compile(
    r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{22,}\b"
)

_AWS_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")

# A `<name that looks like api_key/token/secret> <:|=> <value>` assignment, in
# any language -- the value is either a quoted string of at least 8 characters,
# or an unquoted run of at least 8 word-ish characters that contains a digit
# and isn't immediately followed by `(` or another word character, so a plain
# identifier or function call (`token = generate_token()`) is left alone.
_GENERIC_ASSIGNMENT = re.compile(
    r"""
    (?P<key>[A-Za-z0-9_]*(?:api[_-]?key|token|secret))\b
    (?P<sep>\s*[:=]\s*)
    (?:
        (?P<quote>["'])(?P<qvalue>[^"'\n]{8,})(?P=quote)
      |
        (?P<value>(?=[A-Za-z0-9_.\-+/]*\d)[A-Za-z0-9_.\-+/]{8,})(?![(\w])
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _redact_generic_assignment(match: re.Match[str]) -> str:
    quote = match["quote"] or ""
    return f"{match['key']}{match['sep']}{quote}{_REDACTED}{quote}"


def redact_secrets(text: str) -> str:
    """Mask likely secrets in `text`, preserving everything else unchanged.

    Runs a small, fixed set of high-confidence patterns over `text` -- PEM
    private-key blocks, JWTs, GitHub tokens, AWS access keys, and generic
    `api_key=`/`token=`/`secret=` assignments -- replacing each match (just
    the secret value, for the assignment case) with `[REDACTED]`. Text with
    no matches passes through byte-for-byte unchanged. This is a fixed
    pattern set, not exhaustive secret detection: false negatives (a real
    secret in an unrecognized shape) are the accepted failure mode, in
    exchange for never mangling unrelated text with a false positive.
    """
    text = _PEM_BLOCK.sub(_REDACTED, text)
    text = _JWT.sub(_REDACTED, text)
    text = _GITHUB_TOKEN.sub(_REDACTED, text)
    text = _AWS_ACCESS_KEY.sub(_REDACTED, text)
    text = _GENERIC_ASSIGNMENT.sub(_redact_generic_assignment, text)
    return text
