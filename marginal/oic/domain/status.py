"""Allowed status transitions for claims and investigations, and supersession."""

from __future__ import annotations

from datetime import datetime

from marginal.oic.domain.schema import Claim, ClaimStatus, Investigation, InvestigationStatus

__all__ = [
    "CLAIM_TRANSITIONS",
    "INVESTIGATION_TRANSITIONS",
    "IllegalTransitionError",
    "supersede",
    "transition_claim",
    "transition_investigation",
]


class IllegalTransitionError(ValueError):
    """A status change the lifecycle does not allow."""


_C = ClaimStatus
CLAIM_TRANSITIONS: dict[ClaimStatus, frozenset[ClaimStatus]] = {
    _C.PROPOSED: frozenset({_C.ACTIVE, _C.REJECTED}),
    _C.ACTIVE: frozenset({_C.DISPUTED, _C.STALE, _C.SUPERSEDED, _C.RETRACTED}),
    _C.DISPUTED: frozenset({_C.ACTIVE, _C.STALE, _C.SUPERSEDED, _C.RETRACTED}),
    _C.STALE: frozenset({_C.ACTIVE, _C.DISPUTED, _C.SUPERSEDED, _C.RETRACTED}),
    _C.SUPERSEDED: frozenset(),
    _C.REJECTED: frozenset(),
    _C.RETRACTED: frozenset(),
}

_I = InvestigationStatus
INVESTIGATION_TRANSITIONS: dict[InvestigationStatus, frozenset[InvestigationStatus]] = {
    _I.CREATED: frozenset({_I.QUEUED, _I.CANCELLED}),
    _I.QUEUED: frozenset({_I.RUNNING, _I.CANCELLED}),
    # RUNNING -> QUEUED is a worker whose lease expired handing the job back.
    _I.RUNNING: frozenset(
        {
            _I.QUEUED,
            _I.WAITING_FOR_USER,
            _I.WAITING_FOR_APPROVAL,
            _I.PAUSED,
            _I.COMPLETED,
            _I.FAILED,
            _I.CANCELLED,
        }
    ),
    _I.WAITING_FOR_USER: frozenset({_I.QUEUED, _I.CANCELLED}),
    _I.WAITING_FOR_APPROVAL: frozenset({_I.QUEUED, _I.COMPLETED, _I.CANCELLED}),
    _I.PAUSED: frozenset({_I.QUEUED, _I.CANCELLED}),
    _I.FAILED: frozenset({_I.QUEUED}),
    _I.COMPLETED: frozenset(),
    _I.CANCELLED: frozenset(),
}


def transition_claim(claim: Claim, to: ClaimStatus) -> Claim:
    """Return `claim` with status `to`, or raise if the lifecycle forbids it."""
    if to not in CLAIM_TRANSITIONS[claim.status]:
        raise IllegalTransitionError(f"claim {claim.id}: {claim.status.value} -> {to.value}")
    return claim.model_copy(update={"status": to})


def transition_investigation(
    investigation: Investigation, to: InvestigationStatus
) -> Investigation:
    """Return `investigation` with status `to`, or raise if the lifecycle forbids it."""
    if to not in INVESTIGATION_TRANSITIONS[investigation.status]:
        raise IllegalTransitionError(
            f"investigation {investigation.id}: {investigation.status.value} -> {to.value}"
        )
    return investigation.model_copy(update={"status": to})


def supersede(old: Claim, new: Claim, at: datetime) -> tuple[Claim, Claim]:
    """Replace `old` with `new` from valid time `at`, keeping both.

    The old claim's validity closes at `at` and it becomes superseded; the new
    one starts at `at` and points back at the old one. Its `recorded_at` is
    untouched, so learning about a change late stays visible.
    """
    closed = transition_claim(old, ClaimStatus.SUPERSEDED)
    # model_validate, not model_copy, so the valid-interval check runs again.
    closed = Claim.model_validate({**closed.model_dump(), "valid_until": at})
    opened = Claim.model_validate(
        {**new.model_dump(), "valid_from": at, "supersedes_claim_id": old.id}
    )
    return closed, opened
