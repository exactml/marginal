"""Errors raised while loading repo-local configuration."""


class ConfigError(Exception):
    """`.marginal/config.yaml` could not be parsed or failed validation."""


class ConfigParseError(ConfigError):
    """`.marginal/config.yaml` is not valid YAML, or not a mapping at the top level."""


class ConfigValidationError(ConfigError):
    """`.marginal/config.yaml` parsed but failed schema validation."""
