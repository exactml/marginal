# ADR 0002: marginal-action as a composite action

**Status:** Accepted · 2026-09-08 · updated 2026-10-25

## Context

Most teams run marginal in GitHub Actions, on every pull request. Something has
to install marginal, pass it the GitHub token and the model key, and run
`marginal review --comment`. That's `exactml/marginal-action`. GitHub supports
three kinds of action: composite (a list of steps), Docker, and JavaScript.

## Decision

`exactml/marginal-action` is a **composite action** (`runs.using: composite`):
it sets up Python, runs `pip install marginal-review`, and calls the CLI.

## Trade-offs

| Option | Pros | Cons |
|---|---|---|
| **Composite action** (chosen) | Starts fast: no image to build or pull on each run. Works on any GitHub-hosted runner OS, not only Linux. Nothing extra to build, publish, or version beyond the action's own tags. | Less reproducible: the runner's Python and pip aren't pinned the way an image would pin them. |
| Docker action | Fully pinned environment, the same on every run. | Slower start on every PR. Linux runners only. A separate image to build, publish and version. Isolates nothing that marginal needs, since it's pure Python with no system dependencies. |
| JavaScript action | Fastest start, native to Actions. | marginal is Python, so it would still need to install Python and the package, just with extra wrapper code. |

## What this means

- The action's tags (`v1`, `v1.1.2`, …) version the wiring. `marginal-review`
  is versioned separately on PyPI, and the action installs the latest by default.
- Revisit this if marginal ever needs a system dependency that `pip` can't
  install.
- The test repo deliberately doesn't use this action. It installs from git
  instead, so unreleased branches can be tested (see
  [ADR 0007](0007-prove-changes-on-a-real-repo-before-release.md)).

## Accepted in

- [#15 Record marginal-action composite-action decision](https://github.com/exactml/marginal/pull/15)
- [marginal-action #2 Forward provider API keys to marginal review](https://github.com/exactml/marginal-action/pull/2)
- [marginal-action #3 Install provider SDKs alongside marginal-review](https://github.com/exactml/marginal-action/pull/3)
- [marginal-action #4 Skip review on forked PRs missing provider credentials](https://github.com/exactml/marginal-action/pull/4)
