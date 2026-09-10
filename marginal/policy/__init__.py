"""Engineering policy evaluation."""

from __future__ import annotations

import sys
from pathlib import Path


def load_policies(repo_root: str | Path, policy_paths: list[str]) -> list[tuple[str, str]]:
    """Read each of `policy_paths`, resolved relative to `repo_root`.

    Returns `(path, content)` pairs in `policy_paths` order, one per file
    that actually exists. A path that doesn't resolve to a file is skipped
    rather than failing the whole review -- a warning naming the missing
    path is printed to stderr instead.
    """
    root = Path(repo_root)
    policies = []
    for policy_path in policy_paths:
        full_path = root / policy_path
        if not full_path.is_file():
            print(
                f"marginal review: warning: policy file not found, skipping: {policy_path}",
                file=sys.stderr,
            )
            continue
        policies.append((policy_path, full_path.read_text()))
    return policies
