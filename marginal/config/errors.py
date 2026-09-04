"""Errors raised while loading repo-local configuration."""


class ConfigError(Exception):
    """`.marginal/config.yaml` could not be parsed or failed validation."""
