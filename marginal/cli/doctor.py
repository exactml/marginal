"""`marginal doctor`: check the config, credentials, and GitHub access up front."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import requests

from marginal.config.errors import ConfigError
from marginal.config.loader import CONFIG_RELATIVE_PATH, load_config
from marginal.config.schema import MarginalConfig, PermissionsConfig
from marginal.github.client import GitHubClient
from marginal.github.credentials import require_github_token
from marginal.github.errors import GitHubAuthenticationError, GitHubError, GitHubNotFoundError
from marginal.providers.errors import MissingCredentialsError, ProviderError
from marginal.providers.factory import get_provider

# (passed, message, fix): passed is None for a check that was skipped.
Check = tuple[bool | None, str, str | None]


def run_doctor(repo: str | None = None, path: str | Path = ".") -> int:
    """Print one line per setup check, with a fix under each failure.

    Checks that `.marginal/config.yaml` exists and is valid, that
    `models.reviewer` is set, that every configured model's provider is
    usable (SDK installed, API key env var set -- no model is called), that
    the permissions let `marginal review` read the PR (with only a note when
    `write.comments` is off), that `GITHUB_TOKEN` is set, and, with `repo`,
    that GitHub accepts the token and the repository is reachable (one
    read-only request). Nothing is posted.

    Returns 0 if every check passes (a skipped or noted one doesn't count), else 1.
    """
    failed = 0
    for passed, message, fix in _checks(repo, Path(path)):
        if passed is None:
            print(f"- {message}")
        elif passed:
            print(f"✓ {message}")
        else:
            failed += 1
            print(f"✗ {message}")
            if fix:
                print(f"    → {fix}")
    print()
    print("All checks passed." if not failed else f"{failed} check(s) failed.")
    return 1 if failed else 0


def _checks(repo: str | None, path: Path) -> Iterator[Check]:
    config = yield from _config_check(path)
    if config is not None:
        yield from _model_checks(config)
        yield _permissions_check(config.permissions)
    yield from _github_checks(repo, config.permissions if config else PermissionsConfig())


def _config_check(path: Path) -> Iterator[Check]:
    if not (path / CONFIG_RELATIVE_PATH).is_file():
        yield False, ".marginal/config.yaml not found", "run `marginal init` to scaffold it"
        return None
    try:
        config = load_config(path)
    except ConfigError as exc:
        yield False, str(exc), "fix the fields above in .marginal/config.yaml"
        return None
    yield True, ".marginal/config.yaml is valid", None
    return config


def _model_checks(config: MarginalConfig) -> Iterator[Check]:
    if "reviewer" not in config.models:
        yield (
            False,
            "models.reviewer is not set",
            "set models.reviewer's provider and model in .marginal/config.yaml",
        )
    for role, spec in config.models.items():
        # Building a provider reads its API key from the environment but calls nothing,
        # so a new provider is covered here without doctor knowing its key's name.
        try:
            get_provider(spec)
        except MissingCredentialsError as exc:
            yield (
                False,
                f"models.{role}: {exc}",
                "export it in your shell, and add it as a repository secret for CI",
            )
        except ProviderError as exc:
            yield False, f"models.{role}: {exc}", None
        else:
            yield True, f"models.{role}: {spec.provider} / {spec.model} is ready", None


def _permissions_check(permissions: PermissionsConfig) -> Check:
    if not permissions.read.pull_requests:
        return (
            False,
            "permissions.read.pull_requests is off, so `marginal review` can't read the PR",
            "set it to true in .marginal/config.yaml",
        )
    if not permissions.write.comments:
        # Not a failure: reviewing locally without --comment never posts.
        return (
            None,
            "permissions.write.comments is off, so `marginal review --comment` can't post "
            "(fine if you only review locally)",
            None,
        )
    return True, "permissions allow `marginal review --comment`", None


def _github_checks(repo: str | None, permissions: PermissionsConfig) -> Iterator[Check]:
    try:
        require_github_token()
    except GitHubAuthenticationError:
        yield (
            False,
            "GITHUB_TOKEN is not set",
            "export GITHUB_TOKEN=<token> (in Actions, pass secrets.GITHUB_TOKEN)",
        )
        return
    yield True, "GITHUB_TOKEN is set", None

    if repo is None:
        yield None, "Skipped GitHub access (pass --repo owner/name to check it)", None
        return
    try:
        GitHubClient(repo, permissions).get_repository()
    except GitHubAuthenticationError:
        yield (
            False,
            "GitHub rejected GITHUB_TOKEN",
            "the token is invalid or expired; create a new one",
        )
    except GitHubNotFoundError:
        yield (
            False,
            f"{repo} not found, or GITHUB_TOKEN can't see it",
            "check --repo, and that the token has access to the repository",
        )
    except GitHubError as exc:
        yield False, f"GitHub check for {repo} failed: {exc}", None
    except requests.RequestException as exc:
        yield False, f"couldn't reach GitHub: {exc}", "check your network connection"
    else:
        yield True, f"GitHub accepted GITHUB_TOKEN and {repo} is reachable", None
