from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from marginal.oic.domain.schema import (
    Claim,
    ClaimEvidence,
    ClaimLink,
    ClaimLinkType,
    ClaimStatus,
    ClaimType,
    Evidence,
    EvidenceRelation,
    Investigation,
    InvestigationStatus,
    Scope,
    ScopeType,
)
from marginal.oic.domain.status import (
    CLAIM_TRANSITIONS,
    INVESTIGATION_TRANSITIONS,
    IllegalTransitionError,
    supersede,
    transition_claim,
    transition_investigation,
)

JAN_10 = datetime(2026, 1, 10, tzinfo=timezone.utc)
FEB_1 = datetime(2026, 2, 1, tzinfo=timezone.utc)
FEB_5 = datetime(2026, 2, 5, tzinfo=timezone.utc)


def _claim(text="Service A is owned by Team X", **kw):
    return Claim(
        organization_id="org",
        claim_type=ClaimType.OWNERSHIP,
        claim_text=text,
        scope_ids=("repo-a",),
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


@pytest.mark.parametrize(
    ("start", "to"),
    [(s, t) for s, targets in CLAIM_TRANSITIONS.items() for t in targets],
)
def test_every_listed_claim_transition_is_allowed(start, to):
    assert transition_claim(_claim(status=start), to).status is to


@pytest.mark.parametrize(
    ("start", "to"),
    [
        (ClaimStatus.PROPOSED, ClaimStatus.STALE),
        (ClaimStatus.REJECTED, ClaimStatus.ACTIVE),
        (ClaimStatus.SUPERSEDED, ClaimStatus.ACTIVE),
        (ClaimStatus.RETRACTED, ClaimStatus.ACTIVE),
        (ClaimStatus.ACTIVE, ClaimStatus.PROPOSED),
    ],
)
def test_illegal_claim_transition_raises(start, to):
    with pytest.raises(IllegalTransitionError):
        transition_claim(_claim(status=start), to)


def test_claim_transition_does_not_change_the_original():
    claim = _claim()
    transition_claim(claim, ClaimStatus.ACTIVE)
    assert claim.status is ClaimStatus.PROPOSED


def test_investigation_can_wait_for_a_user_and_resume():
    inv = Investigation(organization_id="org", title="t", objective="o", initiated_by="eslem")
    for to in (
        InvestigationStatus.QUEUED,
        InvestigationStatus.RUNNING,
        InvestigationStatus.WAITING_FOR_USER,
        InvestigationStatus.QUEUED,
        InvestigationStatus.RUNNING,
        InvestigationStatus.COMPLETED,
    ):
        inv = transition_investigation(inv, to)
    assert inv.status is InvestigationStatus.COMPLETED


def test_terminal_investigation_statuses_have_no_way_out():
    assert INVESTIGATION_TRANSITIONS[InvestigationStatus.COMPLETED] == frozenset()
    assert INVESTIGATION_TRANSITIONS[InvestigationStatus.CANCELLED] == frozenset()
    inv = Investigation(
        organization_id="org",
        title="t",
        objective="o",
        initiated_by="eslem",
        status=InvestigationStatus.COMPLETED,
    )
    with pytest.raises(IllegalTransitionError):
        transition_investigation(inv, InvestigationStatus.RUNNING)


def test_every_status_has_a_transition_entry():
    assert set(CLAIM_TRANSITIONS) == set(ClaimStatus)
    assert set(INVESTIGATION_TRANSITIONS) == set(InvestigationStatus)


def test_valid_time_and_recorded_time_are_independent():
    claim = _claim(valid_from=FEB_1, recorded_at=FEB_5)
    assert claim.valid_from == FEB_1
    assert claim.recorded_at == FEB_5


def test_valid_until_before_valid_from_is_rejected():
    with pytest.raises(ValidationError, match="valid_until is before valid_from"):
        _claim(valid_from=FEB_5, valid_until=FEB_1)


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValidationError):
        _claim(valid_from=datetime(2026, 2, 1))


def test_claim_needs_an_explicit_scope():
    with pytest.raises(ValidationError):
        Claim(
            organization_id="org",
            claim_type=ClaimType.DESCRIPTIVE,
            claim_text="x",
            scope_ids=(),
            created_by="agent",
        )


def test_confidence_is_optional_and_bounded():
    assert _claim().confidence is None
    with pytest.raises(ValidationError):
        _claim(confidence=1.5)


def test_supersession_closes_the_old_claim_and_keeps_both():
    # Ownership moves to Team Y on Feb 1; marginal learns it on Feb 5.
    old = _claim(status=ClaimStatus.ACTIVE, valid_from=JAN_10, recorded_at=JAN_10)
    new = _claim("Service A is owned by Team Y", recorded_at=FEB_5)

    closed, opened = supersede(old, new, at=FEB_1)

    assert closed.id == old.id
    assert closed.status is ClaimStatus.SUPERSEDED
    assert (closed.valid_from, closed.valid_until) == (JAN_10, FEB_1)
    assert opened.valid_from == FEB_1
    assert opened.recorded_at == FEB_5
    assert opened.supersedes_claim_id == old.id
    assert old.status is ClaimStatus.ACTIVE  # the original object is untouched


def test_only_an_active_like_claim_can_be_superseded():
    with pytest.raises(IllegalTransitionError):
        supersede(_claim(), _claim("y"), at=FEB_1)


def test_supporting_and_contradicting_evidence_coexist_on_one_claim():
    claim = _claim(status=ClaimStatus.ACTIVE)
    pr, incident = _evidence("exactml/x#1"), _evidence("exactml/x#2")
    links = [
        ClaimEvidence(claim_id=claim.id, evidence_id=pr.id, relation=EvidenceRelation.SUPPORTS),
        ClaimEvidence(
            claim_id=claim.id, evidence_id=incident.id, relation=EvidenceRelation.CONTRADICTS
        ),
    ]
    disputed = transition_claim(claim, ClaimStatus.DISPUTED)

    assert {link.relation for link in links} == {
        EvidenceRelation.SUPPORTS,
        EvidenceRelation.CONTRADICTS,
    }
    assert disputed.status is ClaimStatus.DISPUTED


def test_links_are_typed():
    with pytest.raises(ValidationError):
        ClaimEvidence(claim_id="c", evidence_id="e", relation="mentions")
    with pytest.raises(ValidationError):
        ClaimLink(from_claim_id="a", to_claim_id="b", link_type="edge")
    assert ClaimLink(from_claim_id="a", to_claim_id="b", link_type=ClaimLinkType.DEPENDS_ON)


def test_claim_cannot_link_to_itself():
    with pytest.raises(ValidationError):
        ClaimLink(from_claim_id="a", to_claim_id="a", link_type=ClaimLinkType.RELATED_TO)


def test_scopes_nest_but_not_into_themselves():
    org = Scope(organization_id="org", scope_type=ScopeType.ORGANIZATION, scope_key="acme")
    repo = Scope(
        organization_id="org",
        scope_type=ScopeType.REPOSITORY,
        scope_key="acme/api",
        parent_scope_id=org.id,
    )
    assert repo.parent_scope_id == org.id
    with pytest.raises(ValidationError):
        Scope(
            id="s",
            organization_id="org",
            scope_type=ScopeType.TEAM,
            scope_key="t",
            parent_scope_id="s",
        )


def test_domain_objects_are_immutable():
    with pytest.raises(ValidationError):
        _claim().status = ClaimStatus.ACTIVE
