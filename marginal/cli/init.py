"""Scaffold a new repository for marginal: `marginal init`."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml

from marginal.config.schema import MarginalConfig

CONFIG_FILE = Path(".marginal") / "config.yaml"
POLICIES_DIR = Path(".marginal") / "policies"
POLICIES_README = POLICIES_DIR / "README.md"
ANTI_POLICIES_DIR = Path(".marginal") / "anti-policies"
ANTI_POLICIES_README = ANTI_POLICIES_DIR / "README.md"
WORKFLOW_FILE = Path(".github") / "workflows" / "marginal.yml"

InitStatus = Literal["created", "skipped", "overwritten"]

POLICIES_README_TEMPLATE = """\
# Review policies

Add repository-specific review guidance as Markdown files in this directory.
List the files you want `marginal review` to load in `.marginal/config.yaml`
under `policies`.

Suggested files include:

- `security.md` for security and privacy requirements
- `testing.md` for test and coverage expectations
- `architecture.md` for boundaries and design constraints

Keep each policy focused on a rule, its rationale, and the code it applies to.
"""

ANTI_POLICIES_README_TEMPLATE = """\
# Review anti-policies

Add repository-specific anti-policy guidance as Markdown files in this directory.
List the files you want `marginal review` to load in `.marginal/config.yaml`
under `anti_policies`.

Anti-policies document deliberate tradeoffs, accepted technical debt, or
intentional patterns that `marginal review` should never flag as issues.

Suggested files include:

- `tradeoffs.md` for accepted design tradeoffs and known compromises
- `patterns.md` for intentional patterns that reviewers might otherwise question
- `exceptions.md` for deliberate deviations from general guidelines

Keep each anti-policy focused on the accepted pattern, its rationale, and why it is intentional.
"""

WORKFLOW_TEMPLATE = """\
name: marginal

on:
  pull_request:

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: exactml/marginal-action@v1
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
"""


def run_init(path: str | Path = ".", force: bool = False) -> int:
    """Scaffold marginal's config, policy guides, and GitHub workflow under `path`.

    Each artifact is skipped if it already exists, unless `force` is set. A
    forced write is reported as an overwrite so reruns are distinguishable
    from a fresh scaffold. Always returns 0.
    """
    root = Path(path)
    config_yaml = yaml.safe_dump(MarginalConfig().model_dump(mode="json"), sort_keys=False)

    _report(".marginal/config.yaml", _write_file(root / CONFIG_FILE, config_yaml, force))
    _report(".marginal/policies/", _make_dir(root / POLICIES_DIR, force))
    _report(
        ".marginal/policies/README.md",
        _write_file(root / POLICIES_README, POLICIES_README_TEMPLATE, force),
    )
    _report(".marginal/anti-policies/", _make_dir(root / ANTI_POLICIES_DIR, force))
    _report(
        ".marginal/anti-policies/README.md",
        _write_file(root / ANTI_POLICIES_README, ANTI_POLICIES_README_TEMPLATE, force),
    )
    _report(
        ".github/workflows/marginal.yml",
        _write_file(root / WORKFLOW_FILE, WORKFLOW_TEMPLATE, force),
    )

    print()
    print("marginal is ready.")
    return 0


def _write_file(target: Path, content: str, force: bool) -> InitStatus:
    if target.exists():
        if not force:
            return "skipped"
        status: InitStatus = "overwritten"
    else:
        status = "created"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return status


def _make_dir(target: Path, force: bool) -> InitStatus:
    if target.exists():
        if not force:
            return "skipped"
        target.mkdir(parents=True, exist_ok=True)
        return "overwritten"
    target.mkdir(parents=True, exist_ok=True)
    return "created"


def _report(label: str, status: InitStatus) -> None:
    if status == "created":
        print(f"✓ Created {label}")
    elif status == "overwritten":
        print(f"↻ Overwrote {label}")
    else:
        print(f"- Skipped {label} (already exists)")
