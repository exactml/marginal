# ADR 0004: Review rules come from the PR's base commit

**Status:** Accepted · recorded 2026-10-25

## Context

A review is shaped by files in the repository: `.marginal/config.yaml`, the
policy files, and the anti-policy files. Those files live in the same repo as
the code under review, so a pull request can edit them.

If marginal read them from the PR's own checkout, a PR could change the rules
it's reviewed by. For example, one PR could:

- introduce a rounding bug in `pricing.py`, **and**
- set `review.enabled: false`, or add an anti-policy saying "never flag
  rounding changes".

The review would then switch itself off, or be told to look away. This matters
more as coding agents write PRs: an agent asked to "make the review pass" can
do it by editing `.marginal/` instead of fixing the code.

## Decision

`marginal review` and `marginal compact` read config, policies, and
anti-policies **as of the PR's base commit** (`pull_request.base.sha`), through
GitHub's contents API. The PR's checkout is still used for everything that
*is* under review: the diff and the code graph.

One exception: when the base commit has no `.marginal/config.yaml` at all (the
PR that first sets marginal up), the checkout's config is used, so a new
user's first PR gets a review.

When a PR edits anything under `.marginal/`, the review summary says so:
the edits apply after the PR merges.

`marginal doctor` keeps reading the local working tree, because it is a
pre-flight check for files you are editing.

## Trade-offs

| Option | Pros | Cons |
|---|---|---|
| **Base commit** (chosen) | A PR can't loosen its own review. The rules are exactly those the team already merged. Same answer on every re-run of the same PR. | Config changes take effect only after merge, so a PR can't try out new settings on itself. Costs one GitHub API call per config or policy file. |
| PR's own checkout (the old behavior) | Simplest: just read files from disk. A PR can tune settings and see the effect right away. | Any PR can switch its review off, ignore every file, or add an anti-policy that silences a finding. |
| Latest commit on the default branch | Also out of the PR's reach. | Moves while the PR is open, so two runs on the same PR can use different rules. A PR based on an old branch gets reviewed by rules it never saw. |
| Fail when the base has no config | Strictest: never trusts PR-supplied config. | The very first PR that adds marginal would get no review, a bad first experience. Safe to allow, since a base without config has no rules to bypass. |

## What this means

- A team changes marginal's behavior by merging a config change, like any
  other code. The PR that changes it is reviewed under the old rules.
- An invalid config on the base branch fails reviews until it's fixed there.
  The error names the commit it came from.
- The first-setup exception is not a hole: with no config on the base branch,
  there is no reviewer configured and nothing to bypass.

## Accepted in

- [#172 Review a PR with the config and policies on its base commit](https://github.com/exactml/marginal/pull/172)
