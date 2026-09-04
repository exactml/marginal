"""Repository-local configuration loading."""

from marginal.config.errors import ConfigError
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
