# ADR 0007: Prove every change on a real repo, before any release

**Status:** Accepted · recorded 2026-10-25

## Context

Unit tests mock GitHub and the model. They can't show what a team actually
sees on a pull request. Some real bugs only showed up live:

- the model wrote a fragment of its own tool call into a finding's text;
- an empty API key secret produced an error that pointed the wrong way.

The obvious way to test live is to release and install from PyPI. But **a PyPI
version can never be re-uploaded**: a release with a bug stays published
forever, and the only fix is another release. Testing must happen **at branch
level, before any version bump**.

## Decision

**exactml/marginal-client** is a small sample app, set up the way the README
tells a new user to, with one difference: its workflow installs marginal
**from git**, not from PyPI.

- **Every PR there** is reviewed with marginal's current `master`, so a merged
  change is tested on real PRs before it's released.
- **Any marginal branch** can review any marginal-client PR through a manual
  run, with no version bump and no release:
  ```bash
  gh workflow run marginal.yml -R exactml/marginal-client -f ref=<marginal-branch> -f pr=<n>
  ```
- **Scenario PRs** for that check come from `prove-it/<branch>` branches, which
  skip the automatic `master` review. Otherwise `master` would review first,
  and the branch's identical findings would be treated as repeats.
- Its README keeps a **release checklist** of scenarios, from "a real bug" and
  "a clean PR" to "a PR that tries to silence its own review".

On the marginal side, a PR is called ready only with **evidence** in its
description: CI, tests, every marginal finding fixed or answered, a cleanup
pass, and, for any change a team would see on a PR, a real run on
marginal-client with that branch. The `prove-it` skill collects this.

## Trade-offs

| Option | Pros | Cons |
|---|---|---|
| **Sample repo installs from git; any branch on demand** (chosen) | Tests unreleased code on real PRs with the real model and GitHub. No version bump needed, so no permanent PyPI mistakes. Any contributor branch can be checked before merge. | marginal-client doesn't exercise marginal-action itself (marginal's own repo does, on every PR). Manual runs need write access, so outside contributors rely on a maintainer. |
| Test only through PyPI releases (marginal-action) | Exercises exactly what users install. | Every check needs a release. A bad release can't be withdrawn. Branches can't be tested before merge. |
| Add a "git ref" input to marginal-action | One install path for users and tests. | Puts a development feature into the public action. Every user sees an input meant for maintainers. |
| Unit tests only | Fast and free, no secrets needed. | Mocks miss real GitHub and model behavior, which is where the bugs above came from. |

## What this means

- A change a team would see on a PR is checked on marginal-client before it
  merges, and the PR description links the run.
- Releases batch already-proven changes. Cutting one is a packaging step, not
  a test.
- The released path (PyPI plus marginal-action) is still covered: marginal's
  own repo reviews its PRs through marginal-action.

## Accepted in

- [marginal-client #2 Review PRs with marginal installed from git master](https://github.com/exactml/marginal-client/pull/2)
- [#150 Add a prove-it skill that writes merge evidence into the PR body](https://github.com/exactml/marginal/pull/150)
- Applied in [#171](https://github.com/exactml/marginal/pull/171) and [#172](https://github.com/exactml/marginal/pull/172), each with a real run on marginal-client recorded in its description.
