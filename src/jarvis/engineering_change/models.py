"""Program-level engineering lifecycle; WorkItems remain execution truth."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from jarvis.work.models import WorkType


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


class ProcessStageRole(str, Enum):
    """Stable lifecycle role; stage names and WorkTypes remain process-specific."""

    ARCHITECTURE_SOURCE = "architecture_source"
    DEVELOPMENT = "development"


@dataclass(frozen=True, slots=True)
class ProcessStageContract:
    """One registered WorkItem stage inside a governed EngineeringChange process."""

    stage_key: str
    work_type: WorkType
    role: ProcessStageRole

    def __post_init__(self) -> None:
        normalized = str(self.stage_key).strip().lower()
        if not normalized or normalized != self.stage_key:
            raise ValueError("process stage_key must be normalized and non-empty")
        if not isinstance(self.work_type, WorkType):
            raise TypeError("process stage work_type must be WorkType")
        if not isinstance(self.role, ProcessStageRole):
            raise TypeError("process stage role must be ProcessStageRole")
        if self.role is ProcessStageRole.ARCHITECTURE_SOURCE:
            if self.work_type not in {WorkType.RESEARCH, WorkType.DIAGNOSTICS}:
                raise ValueError(
                    "architecture-source stage must use research or diagnostics work"
                )
        elif (
            self.role is ProcessStageRole.DEVELOPMENT
            and self.work_type is not WorkType.DEVELOPMENT
        ):
            raise ValueError("development stage must use development work")


_DEFAULT_PROCESS_STAGES = (
    ProcessStageContract(
        "research",
        WorkType.RESEARCH,
        ProcessStageRole.ARCHITECTURE_SOURCE,
    ),
    ProcessStageContract(
        "development",
        WorkType.DEVELOPMENT,
        ProcessStageRole.DEVELOPMENT,
    ),
)


@dataclass(frozen=True, slots=True)
class ProcessContract:
    """Registered process family with stage semantics and gates owned by JARVIS."""

    key: str
    version: int
    stages: tuple[ProcessStageContract, ...] = _DEFAULT_PROCESS_STAGES

    def __post_init__(self) -> None:
        if (
            not isinstance(self.key, str)
            or not self.key.strip()
            or self.key != self.key.strip().lower()
            or type(self.version) is not int
            or self.version < 1
        ):
            raise ValueError("normalized process key and positive version are required")
        if not isinstance(self.stages, tuple) or not self.stages:
            raise ValueError("process stages must be a non-empty tuple")
        if any(not isinstance(stage, ProcessStageContract) for stage in self.stages):
            raise TypeError("process stages must contain ProcessStageContract values")
        if len({stage.stage_key for stage in self.stages}) != len(self.stages):
            raise ValueError("process stage keys must be unique")
        roles = [stage.role for stage in self.stages]
        if roles.count(ProcessStageRole.ARCHITECTURE_SOURCE) != 1:
            raise ValueError("process requires exactly one architecture-source stage")
        if roles.count(ProcessStageRole.DEVELOPMENT) != 1:
            raise ValueError("process requires exactly one development stage")

    def stage_for_key(self, stage_key: str) -> ProcessStageContract:
        normalized = str(stage_key).strip().lower()
        for stage in self.stages:
            if stage.stage_key == normalized:
                return stage
        raise ChangeConflict(f"unregistered change stage: {stage_key}")

    def stage_for_role(self, role: ProcessStageRole) -> ProcessStageContract:
        if not isinstance(role, ProcessStageRole):
            raise TypeError("role must be ProcessStageRole")
        return next(stage for stage in self.stages if stage.role is role)

    @property
    def architecture_source_stage(self) -> ProcessStageContract:
        return self.stage_for_role(ProcessStageRole.ARCHITECTURE_SOURCE)

    @property
    def development_stage(self) -> ProcessStageContract:
        return self.stage_for_role(ProcessStageRole.DEVELOPMENT)

    @property
    def research_type(self) -> WorkType:
        """Compatibility view for pre-Phase-6 callers."""

        return self.architecture_source_stage.work_type

    @property
    def development_type(self) -> WorkType:
        """Compatibility view for pre-Phase-6 callers."""

        return self.development_stage.work_type


TRANSITIONS: dict[ChangeState, frozenset[ChangeState]] = {
    ChangeState.PROPOSED: frozenset({ChangeState.RESEARCHING, ChangeState.REJECTED}),
    ChangeState.RESEARCHING: frozenset(
        {ChangeState.ARCHITECTURE_READY, ChangeState.FAILED}
    ),
    ChangeState.ARCHITECTURE_READY: frozenset({ChangeState.WAITING_OWNER_APPROVAL}),
    ChangeState.WAITING_OWNER_APPROVAL: frozenset(
        {
            ChangeState.APPROVED_FOR_BUILD,
            ChangeState.REJECTED,
            ChangeState.ARCHITECTURE_READY,
        }
    ),
    ChangeState.APPROVED_FOR_BUILD: frozenset({ChangeState.DEVELOPING}),
    ChangeState.DEVELOPING: frozenset(
        {ChangeState.RESEARCHING, ChangeState.VERIFYING, ChangeState.FAILED}
    ),
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
    plan_artifact_id: str | None = None


class StageAttemptStatus(str, Enum):
    CURRENT = "current"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    REPLACED = "replaced"
    HISTORICAL = "historical"


@dataclass(frozen=True, slots=True)
class ChangeStageAttempt:
    change_id: str
    stage_key: str
    attempt: int
    work_id: str
    status: StageAttemptStatus
    authoritative: bool
    superseded_by_attempt: int | None = None
    produced_artifact_ids: tuple[str, ...] = ()
    plan_artifact_id: str | None = None
