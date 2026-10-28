# ADR 0008: Measure review quality on real upstream PRs, at every release

**Status:** Accepted · recorded 2026-10-28

## Context

A change is proven on marginal-client before it merges (ADR 0007). That shows
the change works. It doesn't show whether **review quality** went up or down
between releases: does marginal still catch real bugs, and does it stay quiet
on clean PRs?

Answering that needs a fixed set of PRs with a known answer, run the same way
at every release, and numbers anyone can compare.

## Decision

**A benchmark of real upstream PRs**, scored by where the findings land.

- **Cases are real PRs from public repos**, pinned by base and head SHA, in
  one file: `tests/integration/review_quality/cases.yml`. A bug case is the PR
  that introduced the bug, with a later fix or revert as evidence, and the
  file, line range, and severity marginal should report. A clean case is a PR
  with nothing to flag. Nothing is copied or forked.
- **No PR and no clone are needed.** `marginal review --base <sha> --head
  <sha>` reads the diff from GitHub's compare API and never posts. The
  benchmark ships its own config, and the runner downloads one snapshot of the
  head SHA for the code graph.
- **Scoring is by location.** A hit is the right file with a line inside the
  expected range. Any finding on a clean case is a false positive. A finding
  elsewhere on a bug case is listed as unlabeled for a person to judge, and
  left out of precision.
- **Each case runs 3 times**, and each metric reports the median and the
  min-max: recall, precision, per-PR accuracy, severity accuracy, time, and
  cost.
- **A soft gate on the release PR.** The `Review quality` workflow runs on
  `release/*` PRs and on demand. It writes the comparison with the last
  release's `baseline.json` to the run summary. It warns, and never fails the
  build.
- **Results ship with the release.** `cut-release` commits the new
  `baseline.json` and the README's **Review quality** table into the release
  PR.

Anyone can propose a case with the **Benchmark case** issue form.

## Trade-offs

| Option | Pros | Cons |
|---|---|---|
| **Real upstream PRs pinned by SHA, reviewed through the compare API** (chosen) | Real bugs that real people wrote and later fixed. Nothing to copy or keep in sync. Adding a case is a few lines of YAML. | Depends on GitHub and the upstream repos staying public. Doesn't exercise posting to a PR (ADR 0007 covers that). |
| Sandbox fork with real PRs opened against it | Runs the full path, posting included. | Every case is a fork and a PR to keep alive. Re-running means re-opening PRs. Slow to grow. |
| Hand-written synthetic cases | Full control over each bug. | Bugs written to be found are easier than real ones. Scores would look better than they are. |
| An LLM judge matches findings to the answer key | Credits a correct finding phrased differently or placed a few lines off. | Adds a second model's noise to every score, and costs more. Location is enough for the first cases. |
| Hard gate: fail the release PR when scores drop | A regression can't ship unnoticed. | Three runs of a model still vary. A noisy drop would block releases, and people learn to ignore a red check. |

## What this means

- Every release PR shows how review quality moved since the last release.
  A maintainer reads it before merging.
- Each version ships with its scores: `baseline.json` and the README table
  change in the same release PR.
- `make test` stays free. `make review-quality` calls the model, needs
  `ANTHROPIC_API_KEY`, and costs money.

## Accepted in

- [#179 Design: release benchmark for review quality and PR experience](https://github.com/exactml/marginal/issues/179)
