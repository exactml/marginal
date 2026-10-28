"""Typed schema for `.marginal/config.yaml`.

These models define structure and defaults only. They intentionally do not
validate the *semantics* of a setting (e.g. whether a `models.*.provider` is
a provider marginal actually supports) — that belongs to the component that
consumes it.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_CONFIG_VERSION = 1


class ReviewTone(str, Enum):
    """Review communication style."""

    CONCISE = "concise"
    DETAILED = "detailed"
    FORMAL = "formal"
    FRIENDLY = "friendly"
    STRICT = "strict"
    EDUCATIONAL = "educational"


# Settings a config may still carry from an older release, and why each went.
_REMOVED_REVIEW_SETTINGS = {
    "confidence_threshold": (
        "findings no longer carry a self-rated confidence; each one quotes its "
        "evidence, and a finding is posted only if marginal finds a quote at its "
        "line and the trigger names real code"
    ),
    "self_reflect": "it was a second model call that only lowered confidence",
}


class ReviewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _reject_removed_settings(cls, data: object) -> object:
        if isinstance(data, dict):
            for key, why in _REMOVED_REVIEW_SETTINGS.items():
                if key in data:
                    raise ValueError(
                        f"review.{key} was removed: {why}. Delete it from .marginal/config.yaml"
                    )
        return data

    enabled: bool = True
    inline_comments: bool = True
    max_comments: int = Field(default=8, gt=0)
    # Ceiling on the built review prompt's estimated size, checked before any
    # model call -- marginal bills the user's own API key, so an unexpectedly
    # huge prompt is skipped rather than paid for. Strict so a stray `true` or
    # `"100k"` is a config error instead of being coerced into a number.
    max_prompt_tokens: int = Field(default=100_000, gt=0, strict=True)
    # Changed files never sent to the model: machine-written, so a finding on
    # them is noise, and often huge, so they'd eat `max_prompt_tokens`. A
    # pattern with no `/` matches the file name in any directory; one with a
    # `/` matches the whole path. Setting this replaces the defaults.
    ignore_paths: list[str] = Field(
        default_factory=lambda: [
            "*.lock",
            "package-lock.json",
            "pnpm-lock.yaml",
            "go.sum",
            "*.min.js",
            "*.min.css",
        ]
    )
    tone: ReviewTone = ReviewTone.CONCISE
    # With `--comment`, these PRs get no review posted and no model call:
    # unfinished (drafts), machine-written (bot authors), or opted out by
    # label. Each one would otherwise spend the team's API key.
    skip_drafts: bool = True
    skip_bots: bool = True
    skip_labels: list[str] = Field(default_factory=lambda: ["skip-review"])


class ContextConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    git_history: bool = True
    code_graph: bool = True
    # Secure default: cross-repository access is permission-controlled and
    # must be turned on explicitly.
    cross_repository: bool = False


class OwnershipConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codeowners: bool = True
    # Secure default: marginal must not notify anyone unless explicitly
    # configured to.
    notify_responsible: bool = False


class ModelSpec(BaseModel):
    """A single model role assignment, parsed structurally only."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url: str | None = None


class PermissionsRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: bool = True
    issues: bool = True
    pull_requests: bool = True


class PermissionsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The one write default that's on — it's the core feature.
    comments: bool = True
    labels: bool = False
    approve: bool = False
    push: bool = False
    merge: bool = False


class PermissionsConfig(BaseModel):
    """Agent permissions. Defaults follow least privilege."""

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
    anti_policies: list[str] = Field(default_factory=list)
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
