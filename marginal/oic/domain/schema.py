"""The OIC knowledge model: claims, evidence, entities, scopes, and investigations.

Pure pydantic. Nothing here knows about a database, an agent runtime or HTTP.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "AgentRun",
    "AgentRunStatus",
    "Checkpoint",
    "Claim",
    "ClaimEvidence",
    "ClaimLink",
    "ClaimLinkType",
    "ClaimStatus",
    "ClaimType",
    "Entity",
    "EntityType",
    "Evidence",
    "EvidenceRelation",
    "Investigation",
    "InvestigationEvent",
    "InvestigationStatus",
    "KnowledgeProposal",
    "Organization",
    "ProposalReviewStatus",
    "ProposalType",
    "ProposalValidationStatus",
    "Relation",
    "Scope",
    "ScopeType",
    "SenderType",
    "ValidationResult",
]


def _new_id() -> str:
    return uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _Model(BaseModel):
    # Frozen: fields can't be reassigned, so a status or time change is a new object.
    # Dict fields aren't deep-frozen; the append-only store keeps history immutable.
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScopeType(str, Enum):
    ORGANIZATION = "organization"
    TEAM = "team"
    PROJECT = "project"
    REPOSITORY = "repository"
    SERVICE = "service"
    DOMAIN = "domain"
    ENVIRONMENT = "environment"
    DATASET = "dataset"
    PIPELINE = "pipeline"
    TEST = "test"


class EntityType(str, Enum):
    SERVICE = "service"
    REPOSITORY = "repository"
    TEAM = "team"
    PIPELINE = "pipeline"
    MODEL = "model"
    DATASET = "dataset"
    TEST = "test"
    CONCEPT = "concept"
    ENVIRONMENT = "environment"
    PERSON = "person"


class ClaimType(str, Enum):
    DESCRIPTIVE = "descriptive"
    NORMATIVE = "normative"
    CAUSAL = "causal"
    HISTORICAL = "historical"
    PROCEDURAL = "procedural"
    OWNERSHIP = "ownership"
    DECISION = "decision"
    OPERATIONAL = "operational"


class ClaimStatus(str, Enum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    DISPUTED = "disputed"
    STALE = "stale"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    RETRACTED = "retracted"


class EvidenceRelation(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"
    CONTEXTUALIZES = "contextualizes"
    SUPERSEDES = "supersedes"
    DERIVED_FROM = "derived_from"


class ClaimLinkType(str, Enum):
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    DEPENDS_ON = "depends_on"
    SPECIALIZES = "specializes"
    GENERALIZES = "generalizes"
    DERIVED_FROM = "derived_from"
    APPLIES_TO = "applies_to"
    CAUSED_BY = "caused_by"
    RELATED_TO = "related_to"


class Relation(str, Enum):
    """The core entity-to-entity relations (ADR 0011): every one can be read from a pull request."""

    PART_OF = "partOf"
    INHERITS = "inherits"
    DEPENDS_ON = "dependsOn"
    INSTALLS = "installs"
    RELEASE_OF = "releaseOf"
    SCHEDULES = "schedules"
    OWNED_BY = "ownedBy"
    DECISION_ABOUT = "decisionAbout"


class InvestigationStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRunStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SenderType(str, Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class ProposalType(str, Enum):
    NEW_ENTITY = "new_entity"
    NEW_CLAIM = "new_claim"
    NEW_EVIDENCE = "new_evidence"
    NEW_RELATIONSHIP = "new_relationship"
    CLAIM_REVISION = "claim_revision"
    CLAIM_DISPUTE = "claim_dispute"
    CLAIM_SUPERSESSION = "claim_supersession"
    CLAIM_REVALIDATION = "claim_revalidation"
    CLAIM_DEPRECATION = "claim_deprecation"


class ProposalValidationStatus(str, Enum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"


class ProposalReviewStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Organization(_Model):
    id: str = Field(default_factory=_new_id)
    name: str
    default_timezone: str = "UTC"
    settings: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=_now)


class Scope(_Model):
    """Where a piece of knowledge applies. Scopes nest through `parent_scope_id`."""

    id: str = Field(default_factory=_new_id)
    organization_id: str
    scope_type: ScopeType
    scope_key: str
    parent_scope_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _not_its_own_parent(self) -> Scope:
        if self.parent_scope_id == self.id:
            raise ValueError("a scope cannot be its own parent")
        return self


class Entity(_Model):
    id: str = Field(default_factory=_new_id)
    organization_id: str
    entity_type: EntityType
    canonical_name: str
    aliases: tuple[str, ...] = ()
    description: str = ""
    scope_ids: tuple[str, ...] = ()
    properties: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=_now)


class Claim(_Model):
    """One structured statement about the org, on two timelines.

    Valid time (`valid_from`/`valid_until`) is when it is true in the org;
    `recorded_at` is when marginal learned it. Ownership that moved on Feb 1
    and was learned on Feb 5 has `valid_from=Feb 1, recorded_at=Feb 5`.
    """

    id: str = Field(default_factory=_new_id)
    organization_id: str
    claim_type: ClaimType
    claim_text: str
    subject_entity_id: str | None = None
    predicate: str | None = None
    object_entity_id: str | None = None
    object_value: str | None = None
    # No default: a claim found in one repo must not silently become org-wide.
    scope_ids: tuple[str, ...] = Field(min_length=1)
    status: ClaimStatus = ClaimStatus.PROPOSED
    # Optional and never the only validity signal: evidence links carry that.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None
    observed_at: AwareDatetime | None = None
    recorded_at: AwareDatetime = Field(default_factory=_now)
    last_verified_at: AwareDatetime | None = None
    review_due_at: AwareDatetime | None = None
    supersedes_claim_id: str | None = None
    created_by: str

    @model_validator(mode="after")
    def _valid_interval(self) -> Claim:
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until is before valid_from")
        return self


class Evidence(_Model):
    """Traceable material: enough to find the original source again, not only a copied excerpt."""

    id: str = Field(default_factory=_new_id)
    organization_id: str
    evidence_type: str
    source_system: str
    source_reference: str
    source_version: str | None = None
    excerpt: str = ""
    content_hash: str | None = None
    observed_at: AwareDatetime | None = None
    recorded_at: AwareDatetime = Field(default_factory=_now)
    collected_by: str
    investigation_id: str | None = None
    scope_ids: tuple[str, ...] = ()
    access_policy_reference: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClaimEvidence(_Model):
    """How one piece of evidence bears on one claim. Conflicting links coexist."""

    claim_id: str
    evidence_id: str
    relation: EvidenceRelation
    rationale: str = ""
    strength: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: AwareDatetime = Field(default_factory=_now)


class ClaimLink(_Model):
    from_claim_id: str
    to_claim_id: str
    link_type: ClaimLinkType
    rationale: str = ""
    created_at: AwareDatetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def _not_self(self) -> ClaimLink:
        if self.from_claim_id == self.to_claim_id:
            raise ValueError("a claim cannot link to itself")
        return self


class Investigation(_Model):
    id: str = Field(default_factory=_new_id)
    organization_id: str
    title: str
    objective: str
    initiated_by: str
    status: InvestigationStatus = InvestigationStatus.CREATED
    priority: int = 0
    scope_ids: tuple[str, ...] = ()
    created_at: AwareDatetime = Field(default_factory=_now)
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    current_checkpoint_id: str | None = None
    failure_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _finishes_after_it_starts(self) -> Investigation:
        if self.started_at and self.completed_at and self.completed_at < self.started_at:
            raise ValueError("completed_at is before started_at")
        return self


class InvestigationEvent(_Model):
    """A durable message or event in an investigation; not canonical knowledge."""

    id: str = Field(default_factory=_new_id)
    investigation_id: str
    sender_type: SenderType
    message_type: str
    content: str
    in_reply_to: str | None = None
    requires_action: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=_now)


class AgentRun(_Model):
    """One provider session inside an investigation; an investigation may have many."""

    id: str = Field(default_factory=_new_id)
    investigation_id: str
    provider: str
    status: AgentRunStatus = AgentRunStatus.RUNNING
    input_checkpoint_id: str | None = None
    output_artifact_ids: tuple[str, ...] = ()
    usage_metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    # Provider session IDs live here only, never on domain objects or in API responses.
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: AwareDatetime = Field(default_factory=_now)
    ended_at: AwareDatetime | None = None


class Checkpoint(_Model):
    """Enough state to resume an investigation in a new agent session."""

    id: str = Field(default_factory=_new_id)
    investigation_id: str
    agent_run_id: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=_now)


class KnowledgeProposal(_Model):
    """Agent output waiting for validation and review; never canonical on its own."""

    id: str = Field(default_factory=_new_id)
    investigation_id: str
    proposal_type: ProposalType
    payload: dict[str, Any]
    validation_status: ProposalValidationStatus = ProposalValidationStatus.PENDING
    validation_errors: tuple[str, ...] = ()
    review_status: ProposalReviewStatus = ProposalReviewStatus.PENDING
    created_at: AwareDatetime = Field(default_factory=_now)
    resolved_at: AwareDatetime | None = None
    resolved_by: str | None = None


class ValidationResult(_Model):
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors
