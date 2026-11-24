# ADR 0013: Check new and bumped dependencies against their public registry

**Status:** Accepted · recorded 2026-11-24

## Context

Coding agents add dependencies freely, and sometimes name a package that
doesn't exist. Attackers watch for those names and register them with code
that runs on install ("slopsquatting"). Typosquats (`reqeusts` for
`requests`) work the same way. A diff alone can't show any of this: the line
`reqeusts==1.0` looks like every other requirement. And a version bump can
change behavior the code relies on, which the diff doesn't show either.

## Decision

For each package a PR adds or bumps in `pyproject.toml`, a requirements file
or `package.json`, the review asks the package's public registry (PyPI or
npm), with **no model call**. A package in the bundled top-5000 list is
never looked up: it exists and is established, and its full record can run
to megabytes.

| Check | Finding |
|---|---|
| The package doesn't exist | High, naming the popular package it may have meant |
| Listed in `dependencies.internal` but also public | High (dependency confusion) |
| An npm security placeholder (`npm/security-holder`) | High |
| One typo from a top-5000 package, first published under a year ago | High under 30 days, else Medium |
| First published under 30 days ago | Medium |

For a **bump**, the GitHub release notes between the two versions, and the
lines in the repository that import the package, go into the existing review
prompt. The model flags a bump only when a change there affects that usage.

These findings quote their manifest line and pass the same evidence check
as the model's. They still post when the prompt is over budget.

## Trade-offs

| Option | Pros | Cons |
|---|---|---|
| **Registry lookups in code, notes in the same prompt** (chosen) | Catches what a diff can't show, in any spelling. No extra model call: a few registry requests, and notes only on PRs that bump. | Sends package names to PyPI, npm and GitHub. Release notes exist only for projects that use GitHub releases. |
| Ask the model whether a package exists | No network code. | A model can't know whether a name was registered last week, and an invented name looks plausible to it too. |
| An external scanner (Socket, Snyk) | Deeper analysis: install scripts, malware signatures. | A separate service and account. marginal's promise is no service of its own. |
| Lookalike on any established package | Catches more. | 3.5% of established PyPI packages (ranked 5,001–15,000) and 1.3% of npm ones are one typo from a top-5000 name (`nose2`, `willow`). Of 80 sampled, none was under a year old, so the age limit removes the noise. |

## What this means

- **Off by default** (`dependencies.check: true` turns it on): package names
  a PR adds or bumps reach PyPI, npm and GitHub, the same requests `pip install`
  or `npm install` would make, and names in `dependencies.internal` are sent
  too, to check whether the name is taken publicly. A team should choose that.
- An unreachable registry skips its checks with a warning; it never fails
  the review.
- Release notes are written by the package's maintainers, so the prompt
  labels them as information, never instructions, and redacts secrets in them.
- The popular-package lists ship with marginal and are refreshed at each
  release (`scripts/refresh_popular_packages.py`).
- Go modules and other ecosystems aren't covered yet.

## Accepted in

- [#156 Check new and bumped dependencies](https://github.com/exactml/marginal/issues/156)
