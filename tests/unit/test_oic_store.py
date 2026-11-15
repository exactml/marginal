"""The OIC store on SQLite, and on Postgres when OIC_TEST_POSTGRES_URL is set.

CI runs SQLite only (ADR 0010). To check Postgres locally:

    docker run -d --rm -p 55432:5432 -e POSTGRES_PASSWORD=pw postgres:16
    OIC_TEST_POSTGRES_URL=postgresql+psycopg://postgres:pw@localhost:55432/postgres pytest
"""

import os
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from marginal.oic.domain.schema import (
    AgentRun,
    Checkpoint,
    Claim,
    ClaimEvidence,
    ClaimLink,
    ClaimLinkType,
    ClaimStatus,
    ClaimType,
    Entity,
    EntityType,
    Evidence,
    EvidenceRelation,
    Investigation,
    InvestigationEvent,
    InvestigationStatus,
    KnowledgeProposal,
    Organization,
    ProposalReviewStatus,
    ProposalType,
    Scope,
    ScopeType,
    SenderType,
)
from marginal.oic.domain.status import (
    IllegalTransitionError,
    supersede,
    transition_claim,
    transition_investigation,
)
from marginal.oic.store.database import alembic_config, open_engine, upgrade
from marginal.oic.store.repositories import InvestigationRepository, KnowledgeRepository
from marginal.oic.store.tables import metadata

JAN_1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
JAN_10 = datetime(2026, 1, 10, tzinfo=timezone.utc)
JAN_15 = datetime(2026, 1, 15, tzinfo=timezone.utc)
FEB_1 = datetime(2026, 2, 1, tzinfo=timezone.utc)
FEB_3 = datetime(2026, 2, 3, tzinfo=timezone.utc)
FEB_5 = datetime(2026, 2, 5, tzinfo=timezone.utc)
FEB_10 = datetime(2026, 2, 10, tzinfo=timezone.utc)

ENGINES = ["sqlite"]
if os.environ.get("OIC_TEST_POSTGRES_URL"):
    ENGINES.append("postgres")


@pytest.fixture(params=ENGINES)
def url(request, tmp_path):
    if request.param == "sqlite":
        yield f"sqlite:///{tmp_path / 'oic.db'}"
        return
    pg = os.environ["OIC_TEST_POSTGRES_URL"]
    command.downgrade(alembic_config(pg), "base")
    yield pg
    command.downgrade(alembic_config(pg), "base")


@pytest.fixture
def engine(url):
    upgrade(url)
    engine = open_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def conn(engine):
    with engine.begin() as conn:
        yield conn


@pytest.fixture
def knowledge(conn):
    repo = KnowledgeRepository(conn)
    repo.add_organization(Organization(id="org", name="Acme"))
    repo.add_scope(
        Scope(id="repo-a", organization_id="org", scope_type=ScopeType.REPOSITORY, scope_key="a")
    )
    repo.add_scope(
        Scope(id="repo-b", organization_id="org", scope_type=ScopeType.REPOSITORY, scope_key="b")
    )
    repo.add_entity(
        Entity(
            id="svc-a",
            organization_id="org",
            entity_type=EntityType.SERVICE,
            canonical_name="Service A",
        )
    )
    return repo


def _claim(text, **kw):
    kw.setdefault("scope_ids", ("repo-a",))
    return Claim(
        organization_id="org",
        claim_type=kw.pop("claim_type", ClaimType.OWNERSHIP),
        claim_text=text,
        created_by="agent",
        **kw,
    )


def _evidence(ref):
    return Evidence(
        organization_id="org",
        evidence_type="pull_request",
        source_system="github",
        source_reference=ref,
        collected_by="agent",
    )


# --- migrations ----------------------------------------------------------------


def test_migrations_build_exactly_the_declared_schema(engine):
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), metadata)
    assert diff == []


def test_migrations_downgrade_to_an_empty_database(url):
    upgrade(url)
    command.downgrade(alembic_config(url), "base")
    engine = open_engine(url)
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()


def test_upgrade_twice_is_a_no_op(url):
    upgrade(url)
    upgrade(url)


# --- claims: append-only versions and two timelines ----------------------------


def test_revising_twice_keeps_three_versions_and_answers_what_was_true(knowledge):
    # Team X owns Service A from Jan 1. Ownership moves to Team Y on Feb 1,
    # and marginal learns that on Feb 5.
    x = _claim("Service A is owned by Team X", subject_entity_id="svc-a", recorded_at=JAN_10)
    knowledge.add_claim(x, by="agent", reason="found in CODEOWNERS", at=JAN_10)
    x = transition_claim(x, ClaimStatus.ACTIVE).model_copy(update={"valid_from": JAN_1})
    knowledge.revise_claim(x, by="eslem", reason="confirmed by the team", at=JAN_10)

    y = _claim("Service A is owned by Team Y", subject_entity_id="svc-a", recorded_at=FEB_5)
    x, y = supersede(x, y, at=FEB_1)
    knowledge.revise_claim(x, by="agent", reason="ownership moved", at=FEB_5)
    knowledge.add_claim(y, by="agent", reason="ownership moved", at=FEB_5)

    history = knowledge.claim_history(x.id)
    assert [v.version for v in history] == [1, 2, 3]
    assert [v.claim.status for v in history] == [
        ClaimStatus.PROPOSED,
        ClaimStatus.ACTIVE,
        ClaimStatus.SUPERSEDED,
    ]
    assert [v.reason for v in history] == [
        "found in CODEOWNERS",
        "confirmed by the team",
        "ownership moved",
    ]

    def owners(at, **kw):
        return [c.claim_text for c in knowledge.claims_valid_at("org", at, **kw)]

    assert owners(JAN_15) == ["Service A is owned by Team X"]
    assert owners(FEB_10) == ["Service A is owned by Team Y"]
    # On Feb 3 marginal still believed Team X owned it, with no end date.
    assert owners(FEB_10, as_of=FEB_3) == ["Service A is owned by Team X"]


def test_claim_as_of_returns_the_version_recorded_by_then(knowledge):
    c = _claim("x")
    knowledge.add_claim(c, by="agent", reason="r", at=JAN_10)
    knowledge.revise_claim(transition_claim(c, ClaimStatus.ACTIVE), by="me", reason="r", at=FEB_1)
    assert knowledge.claim(c.id, as_of=JAN_15).status is ClaimStatus.PROPOSED
    assert knowledge.claim(c.id).status is ClaimStatus.ACTIVE
    assert knowledge.claim(c.id, as_of=JAN_1) is None


def test_unaccepted_claims_are_never_true(knowledge):
    knowledge.add_claim(_claim("proposed"), by="agent", reason="r")
    rejected = _claim("rejected")
    knowledge.add_claim(rejected, by="agent", reason="r")
    knowledge.revise_claim(
        transition_claim(rejected, ClaimStatus.REJECTED), by="eslem", reason="wrong"
    )
    assert knowledge.claims_valid_at("org", FEB_1) == []


def test_claims_filter_by_scope_entity_and_type(knowledge):
    for text, kw in [
        ("a", {"scope_ids": ("repo-a",), "subject_entity_id": "svc-a"}),
        ("b", {"scope_ids": ("repo-b",)}),
        ("ab", {"scope_ids": ("repo-a", "repo-b"), "claim_type": ClaimType.NORMATIVE}),
    ]:
        knowledge.add_claim(_claim(text, status=ClaimStatus.ACTIVE, **kw), by="a", reason="r")

    def texts(**kw):
        return sorted(c.claim_text for c in knowledge.claims_valid_at("org", FEB_1, **kw))

    assert texts(scope_id="repo-a") == ["a", "ab"]
    assert texts(scope_id="repo-b") == ["ab", "b"]
    assert texts(subject_entity_id="svc-a") == ["a"]
    assert texts(claim_type=ClaimType.NORMATIVE) == ["ab"]


def test_revision_refuses_an_illegal_status_change(knowledge):
    c = _claim("x")
    knowledge.add_claim(c, by="agent", reason="r")
    with pytest.raises(IllegalTransitionError):
        knowledge.revise_claim(
            c.model_copy(update={"status": ClaimStatus.STALE}), by="a", reason="r"
        )


def test_revision_needs_an_existing_claim_and_add_needs_a_new_one(knowledge):
    c = _claim("x")
    with pytest.raises(KeyError):
        knowledge.revise_claim(c, by="a", reason="r")
    knowledge.add_claim(c, by="a", reason="r")
    with pytest.raises(ValueError, match="revise it instead"):
        knowledge.add_claim(c, by="a", reason="r")


def test_a_claim_cannot_reference_an_unknown_scope(knowledge):
    with pytest.raises(IntegrityError):
        knowledge.add_claim(_claim("x", scope_ids=("nowhere",)), by="a", reason="r")


def test_times_come_back_timezone_aware(knowledge):
    c = _claim("x", valid_from=JAN_1, recorded_at=JAN_10)
    knowledge.add_claim(c, by="a", reason="r", at=JAN_10)
    stored = knowledge.claim(c.id)
    assert stored == c
    assert stored.valid_from.tzinfo is not None
    assert knowledge.claim_history(c.id)[0].revised_at == JAN_10


# --- evidence ------------------------------------------------------------------


def test_new_evidence_never_removes_older_evidence(knowledge):
    c = _claim("x", status=ClaimStatus.ACTIVE)
    knowledge.add_claim(c, by="a", reason="r")
    pr, incident = _evidence("acme/api#1"), _evidence("acme/api#2")
    knowledge.add_evidence(pr)
    knowledge.link_evidence(
        ClaimEvidence(claim_id=c.id, evidence_id=pr.id, relation=EvidenceRelation.SUPPORTS)
    )
    knowledge.add_evidence(incident)
    knowledge.link_evidence(
        ClaimEvidence(claim_id=c.id, evidence_id=incident.id, relation=EvidenceRelation.CONTRADICTS)
    )

    links = knowledge.evidence_links(c.id)
    assert [(link.evidence_id, link.relation) for link in links] == [
        (pr.id, EvidenceRelation.SUPPORTS),
        (incident.id, EvidenceRelation.CONTRADICTS),
    ]
    assert knowledge.evidence(pr.id) == pr


def test_evidence_and_claim_links_need_existing_claims(knowledge):
    e = _evidence("acme/api#1")
    knowledge.add_evidence(e)
    with pytest.raises(KeyError):
        knowledge.link_evidence(
            ClaimEvidence(claim_id="missing", evidence_id=e.id, relation=EvidenceRelation.SUPPORTS)
        )
    a, b = _claim("a"), _claim("b")
    knowledge.add_claim(a, by="x", reason="r")
    with pytest.raises(KeyError):
        knowledge.link_claims(
            ClaimLink(from_claim_id=a.id, to_claim_id=b.id, link_type=ClaimLinkType.DEPENDS_ON)
        )
    knowledge.add_claim(b, by="x", reason="r")
    link = ClaimLink(from_claim_id=a.id, to_claim_id=b.id, link_type=ClaimLinkType.DEPENDS_ON)
    knowledge.link_claims(link)
    assert knowledge.claim_links(b.id) == [link]


# --- investigations --------------------------------------------------------------


def test_investigation_lifecycle_is_stored_and_checked(knowledge, conn):
    repo = InvestigationRepository(conn)
    inv = Investigation(organization_id="org", title="t", objective="o", initiated_by="eslem")
    repo.add(inv)
    inv = transition_investigation(inv, InvestigationStatus.QUEUED, at=JAN_10)
    repo.save(inv)
    assert repo.get(inv.id).status is InvestigationStatus.QUEUED
    with pytest.raises(IllegalTransitionError):
        repo.save(inv.model_copy(update={"status": InvestigationStatus.COMPLETED}))
    with pytest.raises(KeyError):
        repo.save(Investigation(organization_id="org", title="t", objective="o", initiated_by="e"))


def test_investigation_records_round_trip(knowledge, conn):
    repo = InvestigationRepository(conn)
    inv = Investigation(organization_id="org", title="t", objective="o", initiated_by="eslem")
    repo.add(inv)

    question = InvestigationEvent(
        investigation_id=inv.id,
        sender_type=SenderType.AGENT,
        message_type="question",
        content="Is skipping missing stores intended?",
        requires_action=True,
        created_at=JAN_10,
    )
    answer = InvestigationEvent(
        investigation_id=inv.id,
        sender_type=SenderType.USER,
        message_type="answer",
        content="Yes",
        in_reply_to=question.id,
        created_at=JAN_15,
    )
    repo.add_event(answer)
    repo.add_event(question)
    assert repo.events(inv.id) == [question, answer]

    run = AgentRun(investigation_id=inv.id, provider="fake", runtime_metadata={"session": "s1"})
    repo.add_agent_run(run)
    run = run.model_copy(update={"error": "boom"})
    repo.save_agent_run(run)
    assert repo.agent_runs(inv.id) == [run]

    old = Checkpoint(investigation_id=inv.id, state={"step": 1}, created_at=JAN_10)
    new = Checkpoint(investigation_id=inv.id, state={"step": 2}, created_at=JAN_15)
    repo.add_checkpoint(new)
    repo.add_checkpoint(old)
    assert repo.latest_checkpoint(inv.id) == new

    proposal = KnowledgeProposal(
        investigation_id=inv.id, proposal_type=ProposalType.NEW_CLAIM, payload={"claim_text": "x"}
    )
    repo.add_proposal(proposal)
    proposal = proposal.model_copy(update={"review_status": ProposalReviewStatus.ACCEPTED})
    repo.save_proposal(proposal)
    assert repo.proposals(inv.id) == [proposal]
