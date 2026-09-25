"""Program-level engineering lifecycle; WorkItems remain execution truth."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ChangeConflict(ValueError):
    """A state, identity, or immutable evidence conflict."""


class UnsupportedProcess(ChangeConflict):
    """A process contract is not registered in this runtime."""


class ChangeState(str, Enum):
    PROPOSED = "proposed"
    RESEARCHING = "researching"
    ARCHITECTURE_READY = "architecture_ready"
    WAITING_OWNER_APPROVAL = "waiting_owner_approval"
    APPROVED_FOR_BUILD = "approved_for_build"
    DEVELOPING = "developing"
    VERIFYING = "verifying"
    WAITING_OWNER_ACCEPTANCE = "waiting_owner_acceptance"
    READY_FOR_PROMOTION = "ready_for_promotion"
    WAITING_PROMOTION_APPROVAL = "waiting_promotion_approval"
    PROMOTED = "promoted"
    OBSERVING = "observing"
    CLOSED = "closed"
    BLOCKED_EXTERNAL = "blocked_external"
    REJECTED = "rejected"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"


TRANSITIONS: dict[ChangeState, frozenset[ChangeState]] = {
    ChangeState.PROPOSED: frozenset({ChangeState.RESEARCHING, ChangeState.REJECTED}),
    ChangeState.RESEARCHING: frozenset({ChangeState.ARCHITECTURE_READY}),
    ChangeState.ARCHITECTURE_READY: frozenset({ChangeState.WAITING_OWNER_APPROVAL}),
    ChangeState.WAITING_OWNER_APPROVAL: frozenset(
        {
            ChangeState.APPROVED_FOR_BUILD,
            ChangeState.REJECTED,
            ChangeState.ARCHITECTURE_READY,
        }
    ),
    ChangeState.APPROVED_FOR_BUILD: frozenset({ChangeState.DEVELOPING}),
    ChangeState.DEVELOPING: frozenset({ChangeState.VERIFYING}),
    ChangeState.VERIFYING: frozenset(
        {ChangeState.WAITING_OWNER_ACCEPTANCE, ChangeState.READY_FOR_PROMOTION}
    ),
    ChangeState.WAITING_OWNER_ACCEPTANCE: frozenset(
        {ChangeState.READY_FOR_PROMOTION, ChangeState.REJECTED}
    ),
    ChangeState.READY_FOR_PROMOTION: frozenset(
        {ChangeState.WAITING_PROMOTION_APPROVAL}
    ),
    ChangeState.WAITING_PROMOTION_APPROVAL: frozenset(
        {ChangeState.PROMOTED, ChangeState.REJECTED}
    ),
    ChangeState.PROMOTED: frozenset({ChangeState.OBSERVING, ChangeState.ROLLED_BACK}),
    ChangeState.OBSERVING: frozenset({ChangeState.CLOSED, ChangeState.ROLLED_BACK}),
    ChangeState.BLOCKED_EXTERNAL: frozenset(),
    ChangeState.CLOSED: frozenset(),
    ChangeState.REJECTED: frozenset(),
    ChangeState.FAILED: frozenset(),
    ChangeState.SUPERSEDED: frozenset(),
    ChangeState.ROLLED_BACK: frozenset(),
}


@dataclass(frozen=True, slots=True)
class EngineeringChange:
    change_id: str
    request: str
    process_key: str
    process_version: int
    source_session_id: str
    source_turn_id: str
    state: ChangeState
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ChangeArtifact:
    artifact_id: str
    change_id: str
    kind: str
    revision: int
    digest: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class ChangeStage:
    change_id: str
    stage_key: str
    attempt: int
    work_id: str
