"""Scaffold a new repository for marginal: `marginal init`."""

from __future__ import annotations

from pathlib import Path

import yaml

from marginal.config.schema import MarginalConfig

CONFIG_FILE = Path(".marginal") / "config.yaml"
POLICIES_DIR = Path(".marginal") / "policies"
WORKFLOW_FILE = Path(".github") / "workflows" / "marginal.yml"

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
    """Scaffold `.marginal/config.yaml`, `.marginal/policies/`, and the
    starter GitHub Actions workflow under `path`.

    Each artifact is skipped (not overwritten) if it already exists, unless
    `force` is set. Prints one status line per artifact. Always returns 0.
    """
    root = Path(path)
    config_yaml = yaml.safe_dump(MarginalConfig().model_dump(mode="json"), sort_keys=False)

    _report(".marginal/config.yaml", _write_file(root / CONFIG_FILE, config_yaml, force))
    _report(".marginal/policies/", _make_dir(root / POLICIES_DIR, force))
    _report(
        ".github/workflows/marginal.yml",
        _write_file(root / WORKFLOW_FILE, WORKFLOW_TEMPLATE, force),
    )

    print()
    print("marginal is ready.")
    return 0


def _write_file(target: Path, content: str, force: bool) -> bool:
    if target.exists() and not force:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return True


def _make_dir(target: Path, force: bool) -> bool:
    if target.exists() and not force:
        return False
    target.mkdir(parents=True, exist_ok=True)
    return True


def _report(label: str, created: bool) -> None:
    if created:
        print(f"✓ Created {label}")
    else:
        print(f"- Skipped {label} (already exists)")
