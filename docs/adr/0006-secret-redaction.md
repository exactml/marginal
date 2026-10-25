# ADR 0006: Secret redaction — a few sure patterns, applied to every input

**Status:** Accepted · recorded 2026-10-25

## Context

Everything marginal puts in a prompt goes to a model provider. A diff can
contain a secret: an API key in a config file, a token in a test fixture, a
password inside a URL. So can code marginal reads from outside the diff, like
the caller snippets the code graph adds.

Secret detection always trades two kinds of mistake:

- **Missed secret** (false negative): a real secret reaches the model.
- **False alarm** (false positive): ordinary code gets replaced with
  `[REDACTED]`, so the model reviews a mangled diff and may flag problems
  that aren't there.

## Decision

`redact_secrets` runs a **small, fixed set of high-confidence patterns**:
private-key blocks, JWTs, GitHub tokens, AWS access keys, `api_key=` /
`token=` / `secret=` style assignments, and the `user:password@` part of a URL.
It replaces only the secret part. For example,
`https://user:s3cr3t@host` becomes `https://[REDACTED]@host`, so the model still
sees which host the code talks to.

It runs on **every** text that reaches the model: the diff, caller snippets
from the code graph, and maintainer replies. Fingerprints are computed on the
redacted text too. When the diff had something redacted, the review summary
says so, and names the file.

When a new kind of text is added to the prompt, it goes through
`redact_secrets` as well.

## Trade-offs

| Option | Pros | Cons |
|---|---|---|
| **Few sure patterns, everywhere** (chosen) | Almost never mangles real code. Fast, no dependencies. Easy to test: each pattern has cases that must match and cases that must not. | Misses secrets in unusual shapes, such as a random string in a variable named `x`. |
| Entropy / "looks random" detection | Catches more unusual secrets. | Flags hashes, UUIDs, test data and minified code, which mangles the diff the model has to review. |
| External scanner (e.g. gitleaks) | Large, maintained rule set. | A new dependency to install in every CI run. Rules tuned for blocking commits, not for keeping review input readable. |
| No redaction; rely on the provider's data policy | Nothing to maintain. | Secrets leave the user's infrastructure, which goes against marginal's core promise. |

## What this means

- A missed secret is the accepted failure mode. The pattern set grows when a
  real missed shape shows up, each time with tests.
- Any code path that adds text to a prompt must redact it. Caller snippets
  once skipped this, which is how a secret near a call site could reach the
  model before it was fixed.
- Values with no credentials, such as `TRACKING_URI = "local"`, must pass
  through unchanged, and the tests check for that.

## Accepted in

- [#58 Redact likely secrets from diffs before they reach a model provider](https://github.com/exactml/marginal/pull/58)
- [#171 Redact caller snippets and credentials inside URLs before they reach the model](https://github.com/exactml/marginal/pull/171)
