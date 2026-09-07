"""Repository-local configuration loading."""

from marginal.config.errors import ConfigError, ConfigParseError, ConfigValidationError
from marginal.config.loader import load_config
from marginal.config.schema import (
    ContextConfig,
    MarginalConfig,
    ModelSpec,
    OwnershipConfig,
    PermissionsConfig,
    PermissionsRead,
    PermissionsWrite,
    ReviewConfig,
    ReviewTone,
)

__all__ = [
    "ConfigError",
    "ConfigParseError",
    "ConfigValidationError",
    "ContextConfig",
    "MarginalConfig",
    "ModelSpec",
    "OwnershipConfig",
    "PermissionsConfig",
    "PermissionsRead",
    "PermissionsWrite",
    "ReviewConfig",
    "ReviewTone",
    "load_config",
]
