"""Config and policies as of a pull request's base commit, so a PR can't
change the rules it's reviewed by."""

from __future__ import annotations

import sys
from pathlib import PurePosixPath

from marginal.config.loader import CONFIG_RELATIVE_PATH, load_config, parse_config
from marginal.config.schema import MarginalConfig
from marginal.github.client import GitHubClient
from marginal.policy import load_policies


def load_base_config(
    client: GitHubClient, pull_request: dict[str, object], path: str
) -> tuple[MarginalConfig, str | None]:
    """`.marginal/config.yaml` as of the PR's base commit, and that commit.

    When the base has no config yet -- the PR that first sets marginal up --
    falls back to the one under `path` and returns `None` for the commit.
    """
    base_sha = str(pull_request["base"]["sha"])
    text = client.get_file(CONFIG_RELATIVE_PATH.as_posix(), base_sha)
    if text is None:
        return load_config(path), None
    return parse_config(text, f"{CONFIG_RELATIVE_PATH.as_posix()} at {base_sha[:7]}"), base_sha


def load_base_policies(
    client: GitHubClient, base_sha: str | None, path: str, policy_paths: list[str]
) -> list[tuple[str, str]]:
    """`policy_paths` as of `base_sha`, like `load_policies` reads them under `path`."""
    if base_sha is None:
        return load_policies(path, policy_paths)
    policies = []
    for policy_path in policy_paths:
        # The contents API 404s on `./x`, which a local read accepted.
        content = client.get_file(PurePosixPath(policy_path).as_posix(), base_sha)
        if content is None:
            print(
                f"marginal review: warning: policy file not found, skipping: {policy_path}",
                file=sys.stderr,
            )
            continue
        policies.append((policy_path, content))
    return policies
