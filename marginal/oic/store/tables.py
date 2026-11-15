"""The OIC schema. Column names match the domain fields, so rows map straight to models.

No SQLite-only SQL: the same tables and migrations run on Postgres.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.types import TypeDecorator

__all__ = [
    "agent_runs",
    "checkpoints",
    "claim_evidence",
    "claim_links",
    "claim_version_scopes",
    "claim_versions",
    "entities",
    "evidence",
    "investigation_events",
    "investigations",
    "knowledge_proposals",
    "metadata",
    "organizations",
    "scopes",
]


class UTCDateTime(TypeDecorator):
    """Store datetimes in UTC and read them back timezone-aware, on every engine.

    SQLite drops the timezone, and the domain rejects naive datetimes.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; OIC stores only timezone-aware times")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


ID = String(32)
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def _fk(table: str) -> ForeignKey:
    return ForeignKey(f"{table}.id")


organizations = Table(
    "organizations",
    metadata,
    Column("id", ID, primary_key=True),
    Column("name", Text, nullable=False),
    Column("default_timezone", String(64), nullable=False),
    Column("settings", JSON, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
)

scopes = Table(
    "scopes",
    metadata,
    Column("id", ID, primary_key=True),
    Column("organization_id", ID, _fk("organizations"), nullable=False),
    Column("scope_type", String(32), nullable=False),
    Column("scope_key", Text, nullable=False),
    Column("parent_scope_id", ID, _fk("scopes")),
    Column("metadata", JSON, nullable=False),
    UniqueConstraint("organization_id", "scope_type", "scope_key"),
)

entities = Table(
    "entities",
    metadata,
    Column("id", ID, primary_key=True),
    Column("organization_id", ID, _fk("organizations"), nullable=False),
    Column("entity_type", String(32), nullable=False),
    Column("canonical_name", Text, nullable=False),
    Column("aliases", JSON, nullable=False),
    Column("description", Text, nullable=False),
    Column("scope_ids", JSON, nullable=False),
    Column("properties", JSON, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    Index(None, "organization_id", "entity_type"),
)

# Append-only: a revision is a new (id, version) row; no row is ever updated.
claim_versions = Table(
    "claim_versions",
    metadata,
    Column("id", ID, primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("organization_id", ID, _fk("organizations"), nullable=False),
    Column("claim_type", String(32), nullable=False),
    Column("claim_text", Text, nullable=False),
    Column("subject_entity_id", ID, _fk("entities")),
    Column("predicate", Text),
    Column("object_entity_id", ID, _fk("entities")),
    Column("object_value", Text),
    Column("scope_ids", JSON, nullable=False),
    Column("status", String(32), nullable=False),
    Column("confidence", Float),
    Column("valid_from", UTCDateTime),
    Column("valid_until", UTCDateTime),
    Column("observed_at", UTCDateTime),
    Column("recorded_at", UTCDateTime, nullable=False),
    Column("last_verified_at", UTCDateTime),
    Column("review_due_at", UTCDateTime),
    Column("supersedes_claim_id", ID),
    Column("created_by", Text, nullable=False),
    # Who wrote this version, when, why, and which investigation caused it.
    Column("revised_at", UTCDateTime, nullable=False),
    Column("revised_by", Text, nullable=False),
    Column("revision_reason", Text, nullable=False),
    Column("revision_investigation_id", ID, _fk("investigations")),
    Index(None, "organization_id", "status"),
    Index(None, "organization_id", "claim_type"),
    Index(None, "subject_entity_id"),
    Index(None, "object_entity_id"),
    Index(None, "valid_from", "valid_until"),
)

# One row per scope of each claim version, so claims can be found by scope.
claim_version_scopes = Table(
    "claim_version_scopes",
    metadata,
    Column("claim_id", ID, primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("scope_id", ID, _fk("scopes"), primary_key=True),
    ForeignKeyConstraint(["claim_id", "version"], ["claim_versions.id", "claim_versions.version"]),
    Index(None, "scope_id"),
)

evidence = Table(
    "evidence",
    metadata,
    Column("id", ID, primary_key=True),
    Column("organization_id", ID, _fk("organizations"), nullable=False),
    Column("evidence_type", String(64), nullable=False),
    Column("source_system", String(64), nullable=False),
    Column("source_reference", Text, nullable=False),
    Column("source_version", Text),
    Column("excerpt", Text, nullable=False),
    Column("content_hash", String(128)),
    Column("observed_at", UTCDateTime),
    Column("recorded_at", UTCDateTime, nullable=False),
    Column("collected_by", Text, nullable=False),
    Column("investigation_id", ID, _fk("investigations")),
    Column("scope_ids", JSON, nullable=False),
    Column("access_policy_reference", Text),
    Column("metadata", JSON, nullable=False),
    Index(None, "organization_id", "source_system"),
)

claim_evidence = Table(
    "claim_evidence",
    metadata,
    Column("claim_id", ID, primary_key=True),
    Column("evidence_id", ID, _fk("evidence"), primary_key=True),
    Column("relation", String(32), primary_key=True),
    Column("rationale", Text, nullable=False),
    Column("strength", Float),
    Column("created_at", UTCDateTime, nullable=False),
    Index(None, "evidence_id"),
)

claim_links = Table(
    "claim_links",
    metadata,
    Column("from_claim_id", ID, primary_key=True),
    Column("to_claim_id", ID, primary_key=True),
    Column("link_type", String(32), primary_key=True),
    Column("rationale", Text, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    Index(None, "to_claim_id"),
)

investigations = Table(
    "investigations",
    metadata,
    Column("id", ID, primary_key=True),
    Column("organization_id", ID, _fk("organizations"), nullable=False),
    Column("title", Text, nullable=False),
    Column("objective", Text, nullable=False),
    Column("initiated_by", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column("priority", Integer, nullable=False),
    Column("scope_ids", JSON, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    Column("started_at", UTCDateTime),
    Column("completed_at", UTCDateTime),
    Column("current_checkpoint_id", ID),
    Column("failure_reason", Text),
    Column("metadata", JSON, nullable=False),
    Index(None, "organization_id", "status"),
)

investigation_events = Table(
    "investigation_events",
    metadata,
    Column("id", ID, primary_key=True),
    Column("investigation_id", ID, _fk("investigations"), nullable=False),
    Column("sender_type", String(16), nullable=False),
    Column("message_type", String(64), nullable=False),
    Column("content", Text, nullable=False),
    Column("in_reply_to", ID),
    Column("requires_action", Boolean, nullable=False),
    Column("metadata", JSON, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    Index(None, "investigation_id", "created_at"),
)

agent_runs = Table(
    "agent_runs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("investigation_id", ID, _fk("investigations"), nullable=False),
    Column("provider", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("input_checkpoint_id", ID),
    Column("output_artifact_ids", JSON, nullable=False),
    Column("usage_metadata", JSON, nullable=False),
    Column("error", Text),
    Column("runtime_metadata", JSON, nullable=False),
    Column("started_at", UTCDateTime, nullable=False),
    Column("ended_at", UTCDateTime),
    Index(None, "investigation_id"),
)

checkpoints = Table(
    "checkpoints",
    metadata,
    Column("id", ID, primary_key=True),
    Column("investigation_id", ID, _fk("investigations"), nullable=False),
    Column("agent_run_id", ID, _fk("agent_runs")),
    Column("state", JSON, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    Index(None, "investigation_id", "created_at"),
)

knowledge_proposals = Table(
    "knowledge_proposals",
    metadata,
    Column("id", ID, primary_key=True),
    Column("investigation_id", ID, _fk("investigations"), nullable=False),
    Column("proposal_type", String(32), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("validation_status", String(16), nullable=False),
    Column("validation_errors", JSON, nullable=False),
    Column("review_status", String(16), nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    Column("resolved_at", UTCDateTime),
    Column("resolved_by", Text),
    Index(None, "investigation_id"),
    Index(None, "review_status"),
)
