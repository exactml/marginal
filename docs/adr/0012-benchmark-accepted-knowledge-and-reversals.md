# ADR 0012: Benchmark accepted knowledge, and PRs that break it

**Status:** Accepted · recorded 2026-11-23 · amends ADR 0008

## Context

Since 0.4.0 a review loads the rules and decisions a team accepted from
`.marginal/knowledge/` at the PR's base commit, and with `proposals.enabled`
it reports the rules and decisions a PR states. The benchmark (ADR 0008)
measured neither:

- Its upstream repos have no `.marginal/knowledge/`, so no case ever loaded
  accepted knowledge. Nothing showed whether loading it hurts bug-finding, or
  whether it helps catch what it's for: a PR that breaks an earlier decision
  that its author and reviewers had forgotten.
- Its config left `proposals` off, so the knowledge a review reports was
  never scored.

## Decision

- **A `reversal` case kind.** The PR broke a rule or decision an earlier PR
  stated, and a later fix or revert proves it was a regression. The case
  carries that rule under `accepted`, with the earlier PR's number. Its
  answer key is the breaking lines, like any bug case. A hit that names the
  earlier PR (`#N`) counts toward **Reversals naming their PR**.
- **Accepted knowledge on every case.** Each case may carry `accepted`
  claims: real rules the repo states at the base commit, about the files the
  PR changes. On non-reversal cases they're unrelated to the bug, so they
  test that loading knowledge doesn't hurt recall or raise false reversals.
- **Each case is a two-commit repository.** The runner downloads the base and
  head snapshots, commits the base with `accepted` written into
  `.marginal/knowledge/`, commits the head on top, and runs `marginal review
  --local HEAD~1`. The review reads knowledge from the base commit, as it
  does from a PR's. Each case's `base` is the merge base, so this diff is the
  same as GitHub's compare. PR-Agent reviews the same cases from the same
  diff, without the knowledge, which it has no way to read.
- **Knowledge is scored by location**, like findings. `must_propose` lists
  the rules and decisions the PR's own diff states, each with the line range
  that states it. A reported one hits when its kind matches and its evidence
  line is in range. Anything else it reports counts as **Invented knowledge**.
  A tool that reports no knowledge is `n/a`, never zero.
- **`proposals: enabled` for marginal's reviews.** One attempt, with
  proposals on: what a team using knowledge gets.

## Trade-offs

| Option | Pros | Cons |
|---|---|---|
| **Seed knowledge into a local two-commit repo** (chosen) | Reviews read knowledge exactly as in production. Every case runs the same way. | Two downloads per case. The diff comes from local git, not GitHub's compare. |
| Keep `--base/--head` and add a test-only way to pass knowledge | One download. | A path production never takes, so it could pass while production breaks. |
| A separate attempt with proposals off | Scores stay comparable with releases before 0.4.0. | Doubles marginal's cost at every release, for a comparison needed once. |
| Match reported knowledge by an LLM judge | Credits a rule worded differently. | A second model's noise and cost. Location is enough, as for findings. |

## What this means

- The first release with this, 0.4.0, re-baselines marginal's line in
  `baseline.json`: its reviews now load knowledge and report it.
- The answer keys (`accepted`, `must_propose`) were drafted from each PR's
  diff and the repo at its base, and checked by a maintainer.
- Supersession (`replaces`) isn't measured yet. It needs cases where a PR
  replaces a decision on purpose.
