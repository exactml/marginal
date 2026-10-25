# ADR 0001: Language and runtime

**Status:** Accepted · 2026-09-04 · updated 2026-10-25

## Context

marginal has to talk to several model providers, parse source code, and
eventually evaluate review quality over many runs. It also ships a command-line
tool. The choice of language decides which SDKs and libraries are within reach,
and whether the CLI and the core can live in one process.

## Decision

Python (3.10 or newer) for everything, the CLI included, in one codebase. It
ships on PyPI as `marginal-review`.

## Trade-offs

| Option | Pros | Cons |
|---|---|---|
| **Python, one codebase** (chosen) | First-party SDKs from every model provider. A strong ecosystem for structured output, evaluation, and data analysis. Parsers for code graphs, starting with the standard library's `ast`. The CLI calls the core directly, in-process. | Users need a Python install (GitHub Actions runners already have one). No single static binary. |
| Go CLI + Python core | One static binary for the CLI, easy to download. | Two languages, with an RPC or subprocess boundary between the CLI and the core for no real gain. Weaker model SDK support in Go. |
| TypeScript / Node | Native fit for GitHub tooling and Actions. | Thinner ecosystem for evaluation and data analysis, which the review-quality benchmarks need. |

## What this means

- marginal installs with `pip install marginal-review`, and marginal-action
  installs it the same way in CI (see [ADR 0002](0002-marginal-action-composite.md)).
- Correction (2026-10-25): the original version of this ADR said marginal
  already ships as a Docker image. It doesn't. It ships on PyPI. The reasoning
  above still holds: a static binary adds little when installing from PyPI is
  one command.

## Accepted in

- [#2 Scaffold project structure and dev tooling](https://github.com/exactml/marginal/pull/2)
- [#6 Implement model provider abstraction (BYOK)](https://github.com/exactml/marginal/pull/6)
