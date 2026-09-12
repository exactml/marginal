---
name: cut-release
description: >-
  Cut a marginal release: bump CHANGELOG.md's `UNDER DEVELOPMENT` header to a
  real version + date, bump `pyproject.toml`, tag it, and draft GitHub release
  notes with a contributor-thanks section pulled from PRs merged since the
  last tag. Publishing (which triggers the PyPI trusted-publish workflow)
  only happens on explicit confirmation, never automatically. Use when the
  user says "cut a release", "release vX.Y.Z", "ship a new version", or asks
  to prepare/draft release notes for the next marginal version.
allowed-tools: Bash, Read, Edit
---

# cut-release — bump, tag, and draft release notes, confirmed before publishing

Creating a GitHub Release with `published` state fires `.github/workflows/publish.yml`,
which publishes to PyPI immediately via trusted publishing. That step is
irreversible (PyPI does not allow re-uploading a version), so everything up
to release creation should be reversible and reviewable, and the actual
publish must be an explicit, confirmed action -- never a default.

## Step 1 — Decide the version number

Read the current `## UNDER DEVELOPMENT marginal vx.x.x, xxxx-xx-xx` section
of `CHANGELOG.md` and the current `version` in `pyproject.toml`.

- If `### Breaking Changes` under `UNDER DEVELOPMENT` has any entries, this is
  a breaking release. Pre-1.0, that means bumping the *minor* (`0.1.x` ->
  `0.2.0`), not the patch -- the project doesn't yet promise patch-level
  compatibility guarantees, but a breaking change is still worth signaling
  above a patch bump.
- Otherwise, bump the patch (`0.1.3` -> `0.1.4`).

**Confirm the version number and date with the user before proceeding** --
this is a real, externally-visible decision, not a mechanical default to
apply silently.

## Step 2 — Bump CHANGELOG.md

The top of `CHANGELOG.md` always looks like this, with some categories
populated and some empty:

```markdown
## UNDER DEVELOPMENT marginal vx.x.x, xxxx-xx-xx

### Breaking Changes

### New Features

- ...entries...

### Improvements

- ...entries...

### Fixes

### Warnings

## marginal v<previous>, <previous date>
...
```

Cutting a release is a mechanical split: the `UNDER DEVELOPMENT` header
stays exactly where it is and keeps its position at the top of the file, but
becomes an **empty** skeleton again (all five category headers, no
entries) -- and everything that *was* under it (all its populated
categories and their bullet entries) moves under a **new** dated section
inserted directly below, in the same category order:

```markdown
## UNDER DEVELOPMENT marginal vx.x.x, xxxx-xx-xx

### Breaking Changes

### New Features

### Improvements

### Fixes

### Warnings

## marginal v<new>, <YYYY-MM-DD>

### Breaking Changes

### New Features

- ...entries that were under UNDER DEVELOPMENT's New Features...

### Improvements

- ...entries that were under UNDER DEVELOPMENT's Improvements...

### Fixes

### Warnings

## marginal v<previous>, <previous date>
...
```

Do this with the Edit tool directly (read the file, move the text) rather
than a scripted regex substitution -- the category boundaries are easy to
get subtly wrong with sed, and this only runs once per release.

## Step 3 — Bump `pyproject.toml`

Update `[project].version` to the new version (no `v` prefix, e.g. `0.1.4`).

## Step 4 — Commit, branch, and open the release PR

Follow the naming pattern used by every prior release
(`release/v0.1.0` .. `release/v0.1.3`):

```bash
git checkout -b release/v<new>
git add CHANGELOG.md pyproject.toml
git commit -m "docs: Cut v<new> release notes

Closes out CHANGELOG.md's UNDER DEVELOPMENT section under a dated
v<new> heading and bumps pyproject.toml to <new>."
git push -u origin release/v<new>
gh pr create --title "docs: Cut v<new> release notes" --body "..."
```

Wait for CI to pass, then **squash-merge** -- this repo is squash-only (all
repos in the `exactml` org are, as of 2026-09-12), even though the four
existing releases predate that policy and used a regular merge commit. Don't
follow the older merge-commit precedent for new releases.

## Step 5 — Gather the contributor-thanks list

Find the previous tag and list every PR merged into `master` since it:

```bash
PREV_TAG=$(gh release list --limit 1 --json tagName --jq '.[0].tagName')
PREV_DATE=$(gh api repos/{owner}/{repo}/commits/$PREV_TAG --jq '.commit.committer.date')
gh pr list --repo {owner}/{repo} --state merged --search "merged:>=$PREV_DATE" \
  --json number,title,author,mergedAt --jq '.[] | "\(.number) \(.author.login)"'
```

Collect the unique set of `author.login` values, excluding bots
(`*[bot]`) and excluding the release PR itself. If the only author in the
set is the repo's own maintainer account (no external contributor), **omit
the thanks section entirely** rather than thanking the maintainer for their
own work -- a thanks section only earns its place once there's an actual
external contributor to name.

## Step 6 — Draft the release notes and tag

```bash
gh release create v<new> \
  --title "marginal v<new>" \
  --target master \
  --draft \
  --notes "..."
```

Always create it as `--draft` first -- this stages the tag and notes
without firing the `published` event (so PyPI publish does not trigger),
and gives the user a chance to review the notes on GitHub before deciding to
publish. Base the notes body on the CHANGELOG entries for this version (not
a copy of the whole CHANGELOG, just this release's section), plus the
contributor-thanks section from Step 5 if non-empty.

## Step 7 — Confirm before publishing

**Never run `gh release edit v<new> --draft=false` (or otherwise publish the
draft) without the user explicitly confirming first.** State plainly that
doing so triggers an immediate, irreversible PyPI publish, and wait for a
clear go-ahead before flipping it live.
