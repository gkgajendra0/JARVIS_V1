"""Canonical provider-neutral work state for persistent JARVIS orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum, IntEnum
from typing import Any


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class WorkState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_RESOURCE = "waiting_resource"
    WAITING_DEPENDENCY = "waiting_dependency"
    WAITING_UNTIL = "waiting_until"
    WAITING_FOR_OWNER = "waiting_for_owner"
    PAUSED = "paused"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


class WorkStepState(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkPriority(IntEnum):
    LOW = 10
    NORMAL = 20
    HIGH = 30
    URGENT = 40


class DeliveryPolicy(str, Enum):
    SILENT = "silent"
    WHEN_IDLE = "when_idle"
    INTERRUPT = "interrupt"


class WorkDeliveryKind(str, Enum):
    OWNER_INPUT = "owner_input"
    COMPLETION = "completion"
    FAILURE = "failure"


class WorkDeliveryState(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"


class WorkType(str, Enum):
    DEVELOPMENT = "development"
    RESEARCH = "research"
    DIAGNOSTICS = "diagnostics"
    HANDS = "hands"
    MONITORING = "monitoring"
    REMINDER = "reminder"
    GENERIC = "generic"


_ALLOWED_TRANSITIONS: dict[WorkState, frozenset[WorkState]] = {
    WorkState.QUEUED: frozenset(
        {
            WorkState.RUNNING,
            WorkState.WAITING_RESOURCE,
            WorkState.WAITING_DEPENDENCY,
            WorkState.WAITING_UNTIL,
            WorkState.PAUSED,
            WorkState.CANCELLED,
            WorkState.FAILED,
        }
    ),
    WorkState.RUNNING: frozenset(
        {
            WorkState.WAITING_RESOURCE,
            WorkState.WAITING_DEPENDENCY,
            WorkState.WAITING_UNTIL,
            WorkState.WAITING_FOR_OWNER,
            WorkState.PAUSED,
            WorkState.RETRYING,
            WorkState.COMPLETED,
            WorkState.FAILED,
            WorkState.CANCELLED,
        }
    ),
    WorkState.WAITING_RESOURCE: frozenset(
        {WorkState.RUNNING, WorkState.PAUSED, WorkState.CANCELLED, WorkState.FAILED}
    ),
    WorkState.WAITING_DEPENDENCY: frozenset(
        {WorkState.RUNNING, WorkState.PAUSED, WorkState.CANCELLED, WorkState.FAILED}
    ),
    WorkState.WAITING_UNTIL: frozenset(
        {WorkState.RUNNING, WorkState.PAUSED, WorkState.CANCELLED, WorkState.FAILED}
    ),
    WorkState.WAITING_FOR_OWNER: frozenset(
        {WorkState.RUNNING, WorkState.PAUSED, WorkState.CANCELLED, WorkState.FAILED}
    ),
    WorkState.PAUSED: frozenset(
        {
            WorkState.QUEUED,
            WorkState.RUNNING,
            WorkState.WAITING_RESOURCE,
            WorkState.WAITING_DEPENDENCY,
            WorkState.WAITING_UNTIL,
            WorkState.WAITING_FOR_OWNER,
            WorkState.CANCELLED,
        }
    ),
    WorkState.RETRYING: frozenset(
        {
            WorkState.RUNNING,
            WorkState.WAITING_RESOURCE,
            WorkState.PAUSED,
            WorkState.FAILED,
            WorkState.CANCELLED,
        }
    ),
    WorkState.COMPLETED: frozenset(),
    WorkState.FAILED: frozenset(),
    WorkState.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class WorkDelivery:
    work_id: str
    kind: WorkDeliveryKind
    message: str
    policy: DeliveryPolicy
    event_key: str
    delivery_id: str = field(default_factory=lambda: _new_id("delivery"))
    state: WorkDeliveryState = WorkDeliveryState.PENDING
    created_at: datetime = field(default_factory=_utc_now)
    delivered_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.work_id.strip():
            raise ValueError("delivery work_id must not be empty")
        if not self.message.strip():
            raise ValueError("delivery message must not be empty")
        if not self.event_key.strip():
            raise ValueError("delivery event_key must not be empty")
        if self.state is WorkDeliveryState.DELIVERED and self.delivered_at is None:
            raise ValueError("delivered notification requires delivered_at")

    def delivered(self) -> WorkDelivery:
        if self.state is WorkDeliveryState.DELIVERED:
            return self
        return replace(
            self,
            state=WorkDeliveryState.DELIVERED,
            delivered_at=_utc_now(),
        )


@dataclass(frozen=True, slots=True)
class WorkStep:
    work_id: str
    kind: str
    summary: str
    state: WorkStepState = WorkStepState.PLANNED
    step_id: str = field(default_factory=lambda: _new_id("step"))
    input_data: dict[str, Any] = field(default_factory=dict)
    observation: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.work_id.strip():
            raise ValueError("work_id must not be empty")
        if not self.kind.strip():
            raise ValueError("step kind must not be empty")
        if not self.summary.strip():
            raise ValueError("step summary must not be empty")
        if self.state is WorkStepState.RUNNING and self.started_at is None:
            raise ValueError("running step requires started_at")
        if (
            self.state in {WorkStepState.COMPLETED, WorkStepState.FAILED}
            and self.completed_at is None
        ):
            raise ValueError("finished step requires completed_at")

    def start(self) -> WorkStep:
        if self.state is not WorkStepState.PLANNED:
            raise ValueError("only planned steps can start")
        return replace(self, state=WorkStepState.RUNNING, started_at=_utc_now())

    def complete(self, observation: dict[str, Any]) -> WorkStep:
        if self.state is not WorkStepState.RUNNING:
            raise ValueError("only running steps can complete")
        return replace(
            self,
            state=WorkStepState.COMPLETED,
            observation=dict(observation),
            completed_at=_utc_now(),
        )

    def fail(self, reason: str) -> WorkStep:
        if self.state is not WorkStepState.RUNNING:
            raise ValueError("only running steps can fail")
        normalized = reason.strip()
        if not normalized:
            raise ValueError("step failure reason must not be empty")
        return replace(
            self,
            state=WorkStepState.FAILED,
            error=normalized,
            completed_at=_utc_now(),
        )


@dataclass(frozen=True, slots=True)
class WorkItem:
    request: str
    work_type: WorkType
    source_session_id: str
    source_turn_id: str
    work_id: str = field(default_factory=lambda: _new_id("work"))
    state: WorkState = WorkState.QUEUED
    priority: WorkPriority = WorkPriority.NORMAL
    delivery_policy: DeliveryPolicy = DeliveryPolicy.WHEN_IDLE
    dependencies: tuple[str, ...] = ()
    paused_from_state: WorkState | None = None
    current_step_id: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    status_detail: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    version: int = 1

    def __post_init__(self) -> None:
        if not self.request.strip():
            raise ValueError("work request must not be empty")
        if not self.source_session_id.strip():
            raise ValueError("source_session_id must not be empty")
        if not self.source_turn_id.strip():
            raise ValueError("source_turn_id must not be empty")
        if self.version <= 0:
            raise ValueError("work version must be positive")
        normalized_dependencies = tuple(
            dict.fromkeys(
                str(item).strip() for item in self.dependencies if str(item).strip()
            )
        )
        if self.work_id in normalized_dependencies:
            raise ValueError("work item cannot depend on itself")
        object.__setattr__(self, "dependencies", normalized_dependencies)
        if self.state is not WorkState.PAUSED and self.paused_from_state is not None:
            raise ValueError("paused_from_state is only valid while work is paused")

    def transition(
        self,
        state: WorkState,
        *,
        status_detail: str | None = None,
        current_step_id: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> WorkItem:
        if state is self.state:
            return self
        if state not in _ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(
                f"invalid work transition: {self.state.value} -> {state.value}"
            )
        normalized_detail = (
            None if status_detail is None else status_detail.strip() or None
        )
        next_result = self.result if result is None else dict(result)
        paused_from_state = self.paused_from_state
        if state is WorkState.PAUSED and self.state is not WorkState.PAUSED:
            paused_from_state = self.state
        elif self.state is WorkState.PAUSED and state is not WorkState.PAUSED:
            paused_from_state = None
        return replace(
            self,
            state=state,
            paused_from_state=paused_from_state,
            status_detail=normalized_detail,
            current_step_id=current_step_id,
            result=next_result,
            updated_at=_utc_now(),
            version=self.version + 1,
        )

    def with_progress(
        self,
        *,
        current_step_id: str | None = None,
        status_detail: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> WorkItem:
        if self.state.terminal:
            raise ValueError("terminal work cannot change progress")
        normalized_detail = (
            None if status_detail is None else status_detail.strip() or None
        )
        next_result = self.result if result is None else dict(result)
        return replace(
            self,
            current_step_id=current_step_id,
            status_detail=normalized_detail,
            result=next_result,
            updated_at=_utc_now(),
            version=self.version + 1,
        )

    def with_priority(self, priority: WorkPriority) -> WorkItem:
        if self.state.terminal:
            raise ValueError("terminal work cannot be reprioritized")
        if priority is self.priority:
            return self
        return replace(
            self,
            priority=priority,
            updated_at=_utc_now(),
            version=self.version + 1,
        )
