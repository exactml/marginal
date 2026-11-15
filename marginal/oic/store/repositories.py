"""Read and write OIC records. The only code that touches the tables.

A repository works on a connection the caller opened, so the caller decides
the transaction: `with engine.begin() as conn: KnowledgeRepository(conn)...`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy import Connection, Table, and_, func, insert, or_, select, update

from marginal.oic.domain.schema import (
    AgentRun,
    Checkpoint,
    Claim,
    ClaimEvidence,
    ClaimLink,
    ClaimStatus,
    ClaimType,
    Entity,
    Evidence,
    Investigation,
    InvestigationEvent,
    KnowledgeProposal,
    Organization,
    Scope,
)
from marginal.oic.domain.status import (
    CLAIM_TRANSITIONS,
    INVESTIGATION_TRANSITIONS,
    IllegalTransitionError,
)
from marginal.oic.store import tables as t

__all__ = ["ClaimVersion", "InvestigationRepository", "KnowledgeRepository"]

M = TypeVar("M", bound=BaseModel)

# Never accepted, so never "true" at any time.
_NOT_KNOWLEDGE = (ClaimStatus.PROPOSED, ClaimStatus.REJECTED, ClaimStatus.RETRACTED)


@dataclass(frozen=True)
class ClaimVersion:
    """One stored version of a claim, with who wrote it, when, why, and from which investigation."""

    claim: Claim
    version: int
    revised_at: datetime
    revised_by: str
    reason: str
    investigation_id: str | None


def _row(model: BaseModel) -> dict:
    return {k: v.value if isinstance(v, Enum) else v for k, v in model.model_dump().items()}


def _model(cls: type[M], row) -> M:
    mapping = row._mapping
    return cls.model_validate({name: mapping[name] for name in cls.model_fields})


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _Repository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def _insert(self, table: Table, model: BaseModel) -> None:
        self.conn.execute(insert(table).values(**_row(model)))

    def _get(self, table: Table, cls: type[M], id_: str) -> M | None:
        row = self.conn.execute(select(table).where(table.c.id == id_)).first()
        return _model(cls, row) if row else None

    def _all(self, cls: type[M], query) -> list[M]:
        return [_model(cls, row) for row in self.conn.execute(query)]

    def _replace(self, table: Table, model: BaseModel) -> None:
        """Update a working record in place; which org or investigation it belongs to is fixed."""
        values = _row(model)
        stored = self.conn.execute(select(table).where(table.c.id == values["id"])).first()
        if stored is None:
            raise KeyError(f"{table.name} {values['id']} doesn't exist")
        for owner in ("organization_id", "investigation_id"):
            if owner in values and values[owner] != stored._mapping[owner]:
                raise ValueError(f"{table.name} {values['id']} can't change its {owner}")
        self.conn.execute(update(table).where(table.c.id == values["id"]).values(**values))

    def _check_refs(self, organization_id: str, what: str, refs: dict[Table, object]) -> None:
        """Refuse references to rows that are missing or in another organization.

        Foreign keys only prove a row exists, and JSON id lists get no check at all.
        """
        outside = []
        for table, ids in refs.items():
            wanted = {i for i in ids if i}
            if not wanted:
                continue
            query = select(table.c.id).where(
                table.c.id.in_(wanted), table.c.organization_id == organization_id
            )
            outside += sorted(wanted - set(self.conn.execute(query).scalars()))
        if outside:
            raise ValueError(
                f"{what} references records outside organization {organization_id}: {outside}"
            )


class KnowledgeRepository(_Repository):
    """Canonical knowledge: organizations, scopes, entities, claims and evidence.

    Claims are append-only versions and evidence is insert-only: nothing here
    updates or deletes a stored claim version or piece of evidence.
    """

    def add_organization(self, organization: Organization) -> None:
        self._insert(t.organizations, organization)

    def organization(self, organization_id: str) -> Organization | None:
        return self._get(t.organizations, Organization, organization_id)

    def add_scope(self, scope: Scope) -> None:
        refs = {t.scopes: (scope.parent_scope_id,)}
        self._check_refs(scope.organization_id, f"scope {scope.id}", refs)
        self._insert(t.scopes, scope)

    def scope(self, scope_id: str) -> Scope | None:
        return self._get(t.scopes, Scope, scope_id)

    def add_entity(self, entity: Entity) -> None:
        self._check_refs(
            entity.organization_id, f"entity {entity.id}", {t.scopes: entity.scope_ids}
        )
        self._insert(t.entities, entity)

    def entity(self, entity_id: str) -> Entity | None:
        return self._get(t.entities, Entity, entity_id)

    def add_claim(
        self,
        claim: Claim,
        *,
        by: str,
        reason: str,
        investigation_id: str | None = None,
        at: datetime | None = None,
    ) -> int:
        """Store a new claim as version 1."""
        if self.claim(claim.id) is not None:
            raise ValueError(f"claim {claim.id} already exists; revise it instead")
        return self._write_version(claim, 1, by, reason, investigation_id, at)

    def revise_claim(
        self,
        claim: Claim,
        *,
        by: str,
        reason: str,
        investigation_id: str | None = None,
        at: datetime | None = None,
    ) -> int:
        """Store `claim` as the next version of the claim with its id. Earlier versions stay."""
        current = self._latest(claim.id)
        if current is None:
            raise KeyError(f"claim {claim.id} doesn't exist")
        if claim.organization_id != current.claim.organization_id:
            raise ValueError(f"claim {claim.id} can't move to another organization")
        before, after = current.claim.status, claim.status
        if after != before and after not in CLAIM_TRANSITIONS[before]:
            raise IllegalTransitionError(f"claim {claim.id}: {before.value} -> {after.value}")
        # Two concurrent revisions both pick this number; the primary key rejects the second.
        return self._write_version(claim, current.version + 1, by, reason, investigation_id, at)

    def claim(self, claim_id: str, *, as_of: datetime | None = None) -> Claim | None:
        """The claim as marginal recorded it most recently, or as of `as_of` if given."""
        latest = self._latest(claim_id, as_of)
        return latest.claim if latest else None

    def claim_history(self, claim_id: str) -> list[ClaimVersion]:
        """Every stored version of a claim, oldest first."""
        cv = t.claim_versions
        rows = self.conn.execute(select(cv).where(cv.c.id == claim_id).order_by(cv.c.version))
        return [self._version(row) for row in rows]

    def claims_valid_at(
        self,
        organization_id: str,
        at: datetime,
        *,
        as_of: datetime | None = None,
        scope_id: str | None = None,
        subject_entity_id: str | None = None,
        claim_type: ClaimType | None = None,
    ) -> list[Claim]:
        """Claims that were true in the org at valid time `at`.

        Uses each claim's latest version recorded by `as_of` (default: now), so
        `as_of` answers "what did marginal believe then". Superseded, stale and
        disputed claims count for the time they were valid; proposed, rejected
        and retracted ones never do.
        """
        cv = t.claim_versions
        latest = select(cv.c.id, func.max(cv.c.version).label("version")).group_by(cv.c.id)
        if as_of is not None:
            latest = latest.where(cv.c.revised_at <= as_of)
        latest = latest.subquery()
        query = (
            select(cv)
            .join(latest, and_(cv.c.id == latest.c.id, cv.c.version == latest.c.version))
            .where(
                cv.c.organization_id == organization_id,
                cv.c.status.not_in([s.value for s in _NOT_KNOWLEDGE]),
                or_(cv.c.valid_from.is_(None), cv.c.valid_from <= at),
                or_(cv.c.valid_until.is_(None), cv.c.valid_until > at),
            )
            .order_by(cv.c.recorded_at, cv.c.id)
        )
        if scope_id is not None:
            cvs = t.claim_version_scopes
            query = query.join(
                cvs, and_(cvs.c.claim_id == cv.c.id, cvs.c.version == cv.c.version)
            ).where(cvs.c.scope_id == scope_id)
        if subject_entity_id is not None:
            query = query.where(cv.c.subject_entity_id == subject_entity_id)
        if claim_type is not None:
            query = query.where(cv.c.claim_type == claim_type.value)
        return self._all(Claim, query)

    def add_evidence(self, evidence: Evidence) -> None:
        refs = {t.scopes: evidence.scope_ids, t.investigations: (evidence.investigation_id,)}
        self._check_refs(evidence.organization_id, f"evidence {evidence.id}", refs)
        self._insert(t.evidence, evidence)

    def evidence(self, evidence_id: str) -> Evidence | None:
        return self._get(t.evidence, Evidence, evidence_id)

    def link_evidence(self, link: ClaimEvidence) -> None:
        claim, evidence = self.claim(link.claim_id), self.evidence(link.evidence_id)
        if claim is None:
            raise KeyError(f"claim {link.claim_id} doesn't exist")
        if evidence is None:
            raise KeyError(f"evidence {link.evidence_id} doesn't exist")
        if evidence.organization_id != claim.organization_id:
            raise ValueError("evidence and claim belong to different organizations")
        self._insert(t.claim_evidence, link)

    def evidence_links(self, claim_id: str) -> list[ClaimEvidence]:
        """Every evidence link on a claim, supporting and contradicting alike."""
        ce = t.claim_evidence
        query = select(ce).where(ce.c.claim_id == claim_id).order_by(ce.c.created_at)
        return self._all(ClaimEvidence, query)

    def link_claims(self, link: ClaimLink) -> None:
        source, target = self.claim(link.from_claim_id), self.claim(link.to_claim_id)
        if source is None:
            raise KeyError(f"claim {link.from_claim_id} doesn't exist")
        if target is None:
            raise KeyError(f"claim {link.to_claim_id} doesn't exist")
        if source.organization_id != target.organization_id:
            raise ValueError("linked claims belong to different organizations")
        self._insert(t.claim_links, link)

    def claim_links(self, claim_id: str) -> list[ClaimLink]:
        """Links from or to a claim."""
        cl = t.claim_links
        query = (
            select(cl)
            .where(or_(cl.c.from_claim_id == claim_id, cl.c.to_claim_id == claim_id))
            .order_by(cl.c.created_at)
        )
        return self._all(ClaimLink, query)

    def _latest(self, claim_id: str, as_of: datetime | None = None) -> ClaimVersion | None:
        cv = t.claim_versions
        query = select(cv).where(cv.c.id == claim_id).order_by(cv.c.version.desc()).limit(1)
        if as_of is not None:
            query = query.where(cv.c.revised_at <= as_of)
        row = self.conn.execute(query).first()
        return self._version(row) if row else None

    def _write_version(self, claim, version, by, reason, investigation_id, at) -> int:
        refs = {
            t.scopes: claim.scope_ids,
            t.entities: (claim.subject_entity_id, claim.object_entity_id),
            t.investigations: (investigation_id,),
            t.claim_versions: (claim.supersedes_claim_id,),
        }
        self._check_refs(claim.organization_id, f"claim {claim.id}", refs)
        self.conn.execute(
            insert(t.claim_versions).values(
                **_row(claim),
                version=version,
                revised_at=at or _now(),
                revised_by=by,
                revision_reason=reason,
                revision_investigation_id=investigation_id,
            )
        )
        if claim.scope_ids:
            self.conn.execute(
                insert(t.claim_version_scopes),
                [
                    {"claim_id": claim.id, "version": version, "scope_id": s}
                    for s in dict.fromkeys(claim.scope_ids)  # a repeated scope is one row
                ],
            )
        return version

    @staticmethod
    def _version(row) -> ClaimVersion:
        m = row._mapping
        return ClaimVersion(
            claim=_model(Claim, row),
            version=m["version"],
            revised_at=m["revised_at"],
            revised_by=m["revised_by"],
            reason=m["revision_reason"],
            investigation_id=m["revision_investigation_id"],
        )


class InvestigationRepository(_Repository):
    """Investigations and their events, agent runs, checkpoints and proposals.

    These are working records, not canonical knowledge, so an investigation,
    agent run or proposal is updated in place as it moves through its lifecycle.
    Events and checkpoints are insert-only.
    """

    def add(self, investigation: Investigation) -> None:
        refs = {t.scopes: investigation.scope_ids}
        self._check_refs(investigation.organization_id, f"investigation {investigation.id}", refs)
        self._insert(t.investigations, investigation)

    def get(self, investigation_id: str) -> Investigation | None:
        return self._get(t.investigations, Investigation, investigation_id)

    def save(self, investigation: Investigation) -> None:
        """Store a changed investigation, refusing a status change the lifecycle forbids."""
        stored = self.get(investigation.id)
        if stored is None:
            raise KeyError(f"investigation {investigation.id} doesn't exist")
        before, after = stored.status, investigation.status
        if after != before and after not in INVESTIGATION_TRANSITIONS[before]:
            raise IllegalTransitionError(
                f"investigation {investigation.id}: {before.value} -> {after.value}"
            )
        refs = {t.scopes: investigation.scope_ids}
        self._check_refs(investigation.organization_id, f"investigation {investigation.id}", refs)
        self._replace(t.investigations, investigation)

    def add_event(self, event: InvestigationEvent) -> None:
        self._insert(t.investigation_events, event)

    def events(self, investigation_id: str) -> list[InvestigationEvent]:
        ev = t.investigation_events
        query = (
            select(ev)
            .where(ev.c.investigation_id == investigation_id)
            .order_by(ev.c.created_at, ev.c.id)
        )
        return self._all(InvestigationEvent, query)

    def add_agent_run(self, run: AgentRun) -> None:
        self._insert(t.agent_runs, run)

    def save_agent_run(self, run: AgentRun) -> None:
        self._replace(t.agent_runs, run)

    def agent_runs(self, investigation_id: str) -> list[AgentRun]:
        ar = t.agent_runs
        query = (
            select(ar)
            .where(ar.c.investigation_id == investigation_id)
            .order_by(ar.c.started_at, ar.c.id)
        )
        return self._all(AgentRun, query)

    def add_checkpoint(self, checkpoint: Checkpoint) -> None:
        self._insert(t.checkpoints, checkpoint)

    def latest_checkpoint(self, investigation_id: str) -> Checkpoint | None:
        cp = t.checkpoints
        query = (
            select(cp)
            .where(cp.c.investigation_id == investigation_id)
            .order_by(cp.c.created_at.desc(), cp.c.id.desc())
            .limit(1)
        )
        found = self._all(Checkpoint, query)
        return found[0] if found else None

    def add_proposal(self, proposal: KnowledgeProposal) -> None:
        self._insert(t.knowledge_proposals, proposal)

    def save_proposal(self, proposal: KnowledgeProposal) -> None:
        self._replace(t.knowledge_proposals, proposal)

    def proposals(self, investigation_id: str) -> list[KnowledgeProposal]:
        kp = t.knowledge_proposals
        query = (
            select(kp)
            .where(kp.c.investigation_id == investigation_id)
            .order_by(kp.c.created_at, kp.c.id)
        )
        return self._all(KnowledgeProposal, query)
