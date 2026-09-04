"""Typed schema for `.marginal/config.yaml` (REQUIREMENTS.md §6, §28).

These models define structure and defaults only. They intentionally do not
validate the *semantics* of a setting (e.g. whether a `models.*.provider` is
a provider marginal actually supports) — that belongs to the component that
consumes it.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

SUPPORTED_CONFIG_VERSION = 1


class ReviewTone(str, Enum):
    """Review communication style (REQUIREMENTS.md §13)."""

    CONCISE = "concise"
    DETAILED = "detailed"
    FORMAL = "formal"
    FRIENDLY = "friendly"
    STRICT = "strict"
    EDUCATIONAL = "educational"


class ReviewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    inline_comments: bool = True
    confidence_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    max_comments: int = Field(default=8, gt=0)
    tone: ReviewTone = ReviewTone.CONCISE


class ContextConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    git_history: bool = True
    code_graph: bool = True
    # Secure default: cross-repository access is permission-controlled (§10)
    # and must be turned on explicitly.
    cross_repository: bool = False


class OwnershipConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codeowners: bool = True
    # Secure default: marginal must not notify anyone unless explicitly
    # configured to (§20).
    notify_responsible: bool = False


class ModelSpec(BaseModel):
    """A single model role assignment. Parsed structurally only — see §4/§5."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)


class PermissionsRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: bool = True
    issues: bool = True
    pull_requests: bool = True


class PermissionsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The one write default that's on — it's the core feature (§28).
    comments: bool = True
    labels: bool = False
    approve: bool = False
    push: bool = False
    merge: bool = False


class PermissionsConfig(BaseModel):
    """Agent permissions (§28). Defaults follow least privilege."""

    model_config = ConfigDict(extra="forbid")

    read: PermissionsRead = Field(default_factory=PermissionsRead)
    write: PermissionsWrite = Field(default_factory=PermissionsWrite)


class MarginalConfig(BaseModel):
    """Root of `.marginal/config.yaml`."""

    model_config = ConfigDict(extra="forbid")

    version: int = SUPPORTED_CONFIG_VERSION
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    ownership: OwnershipConfig = Field(default_factory=OwnershipConfig)
    models: dict[str, ModelSpec] = Field(default_factory=dict)
    policies: list[str] = Field(default_factory=list)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)

    @field_validator("version")
    @classmethod
    def _check_supported_version(cls, version: int) -> int:
        if version != SUPPORTED_CONFIG_VERSION:
            raise ValueError(
                f"unsupported config version {version!r} "
                f"(marginal currently supports version {SUPPORTED_CONFIG_VERSION})"
            )
        return version
