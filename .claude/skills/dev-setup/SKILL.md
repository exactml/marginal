---
name: dev-setup
description: >-
  Interactive, self-verifying setup of a local marginal dev environment --
  creates or reuses a `.venv`, installs the package in editable mode with the
  `dev` extras, and installs the pre-commit hook, checking each step actually
  worked instead of assuming it did. Wraps the manual steps already documented
  in CONTRIBUTING.md into one guided flow. Use when a contributor says "set up
  my dev environment", "get me set up to contribute to marginal", "install
  marginal for development", or is about to touch this repo for the first
  time.
allowed-tools: Bash, Read
---

# dev-setup — get a working marginal dev environment, verified

Every step below has a corresponding check. Don't move to the next step
until the current one is confirmed -- a `pip install` that silently no-ops
or installs into the wrong interpreter is the usual way "it's set up" turns
out to be false.

## Step 1 — Check the Python version

`pyproject.toml` requires `>=3.10`.

```bash
python3 --version
```

If it's below 3.10, stop and tell the user which interpreter to use instead
(e.g. `python3.11 -m venv .venv` in every step below) -- don't silently
create a venv that will fail `pip install -e ".[dev]"` later with a cryptic
resolver error.

## Step 2 — Create or reuse `.venv`

Check whether one already exists before creating it -- don't clobber a
contributor's existing environment:

```bash
test -f .venv/pyvenv.cfg && echo "existing venv found" || echo "no venv yet"
```

- If it exists, reuse it as-is.
- If not, create it: `python3 -m venv .venv`.

Either way, confirm it's valid before moving on:

```bash
.venv/bin/python --version
```

## Step 3 — Install the package with dev extras

```bash
.venv/bin/pip install -e ".[dev]"
```

Verify it actually landed in *this* venv, at the version in `pyproject.toml`,
not some other environment on `$PATH`:

```bash
.venv/bin/pip show marginal-review | grep -E "^(Name|Version|Location)"
.venv/bin/ruff --version
.venv/bin/pytest --version
.venv/bin/marginal --help >/dev/null && echo "marginal console script OK"
```

If any of these fail (import error, wrong version, command not found), the
install didn't take -- report the actual error rather than retrying blindly.

## Step 4 — Install the pre-commit hook

Optional per CONTRIBUTING.md, but do it unless the user says not to --
running lint only in CI means a whole round trip to catch what a hook would
have caught locally in a second.

```bash
.venv/bin/pip install pre-commit
.venv/bin/pre-commit install
```

Verify the hook is actually wired into this repo's git, not just installed
as a package:

```bash
test -f .git/hooks/pre-commit && grep -q "pre-commit" .git/hooks/pre-commit && echo "hook installed"
```

## Step 5 — Report the final state plainly

State, in a few lines: the Python version in the venv, the installed
`marginal-review` version, and whether the pre-commit hook is active. If any
step above couldn't be verified, say so explicitly instead of reporting
success -- this skill exists specifically so "it's set up" is checked, not
assumed.
