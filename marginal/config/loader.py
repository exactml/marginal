"""Load and validate `.marginal/config.yaml` from a repository."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from marginal.config.errors import ConfigError
from marginal.config.schema import MarginalConfig

CONFIG_RELATIVE_PATH = Path(".marginal") / "config.yaml"


def load_config(repo_root: str | Path = ".") -> MarginalConfig:
    """Load, parse, and validate `<repo_root>/.marginal/config.yaml`.

    Returns a fully-defaulted `MarginalConfig` if the file does not exist —
    a repository-local config is optional. Raises `ConfigError` if the file
    exists but is not valid YAML, is not a mapping, or fails schema
    validation.
    """
    config_path = Path(repo_root) / CONFIG_RELATIVE_PATH
    if not config_path.is_file():
        return MarginalConfig()

    try:
        raw = yaml.safe_load(config_path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"{config_path}: invalid YAML\n{exc}") from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{config_path}: expected a YAML mapping at the top level, got {type(raw).__name__}"
        )

    try:
        return MarginalConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(config_path, exc)) from exc


def _format_validation_error(config_path: Path, exc: ValidationError) -> str:
    lines = [f"{config_path}: invalid configuration"]
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"]) or "<root>"
        lines.append(f"  - {field}: {error['msg']}")
    return "\n".join(lines)
