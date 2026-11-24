"""Repository-local configuration loading."""

from marginal.config.errors import ConfigError, ConfigParseError, ConfigValidationError
from marginal.config.loader import load_config
from marginal.config.schema import (
    ContextConfig,
    DependenciesConfig,
    MarginalConfig,
    ModelSpec,
    OwnershipConfig,
    PermissionsConfig,
    PermissionsRead,
    PermissionsWrite,
    ProposalsConfig,
    ReviewConfig,
    ReviewTone,
)

__all__ = [
    "ConfigError",
    "ConfigParseError",
    "ConfigValidationError",
    "ContextConfig",
    "DependenciesConfig",
    "MarginalConfig",
    "ModelSpec",
    "OwnershipConfig",
    "PermissionsConfig",
    "PermissionsRead",
    "PermissionsWrite",
    "ProposalsConfig",
    "ReviewConfig",
    "ReviewTone",
    "load_config",
]
