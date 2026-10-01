"""Restart-safe exact continuation coordination for blocked GICC plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .models import (
    ContinuationBlockerType,
    ContinuationState,
    GoalContinuationV1,
    InformationNeedState,
    OwnerGoalV2,
    PlanGraphV1,
)
from .store import GoalStore, GoalStoreConflict, GoalStoreError


class BlockerVerifier(Protocol):
    def __call__(
        self,
        blocker_type: ContinuationBlockerType,
        blocker_id: str,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class ContinuationResumeResult:
    continuation: GoalContinuationV1
    resumed: bool
    reason: str


class ContinuationCoordinator:
    """Create and resume only exact, durably-bound goal continuations."""

    def __init__(self, store: GoalStore) -> None:
        if not isinstance(store, GoalStore):
            raise TypeError("store must be GoalStore")
        self._store = store

    def block(
        self,
        *,
        goal: OwnerGoalV2,
        plan: PlanGraphV1,
        blocked_by_type: ContinuationBlockerType,
        blocked_by_id: str,
        resume_node_id: str,
        work_ids: tuple[str, ...] | list[str] = (),
        created_at: str | None = None,
    ) -> GoalContinuationV1:
        if not isinstance(goal, OwnerGoalV2):
            raise TypeError("goal must be OwnerGoalV2")
        if not isinstance(plan, PlanGraphV1):
            raise TypeError("plan must be PlanGraphV1")
        if plan.goal_id != goal.goal_id:
            raise GoalStoreConflict("continuation plan does not belong to owner goal")
        if plan.goal_revision != goal.goal_revision:
            raise GoalStoreConflict(
                "continuation plan does not bind the current owner-goal revision"
            )
        if resume_node_id not in {node.node_id for node in plan.nodes}:
            raise GoalStoreConflict("continuation resume node is not in plan")
        continuation = GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id=plan.plan_id,
            blocked_by_type=blocked_by_type,
            blocked_by_id=blocked_by_id,
            resume_node_id=resume_node_id,
            work_ids=tuple(work_ids),
            goal_revision=goal.goal_revision,
            created_at=created_at,
        )
        return self._store.put_continuation(continuation)

    def restore(self, continuation_id: str) -> GoalContinuationV1:
        continuation = self._store.get_continuation(str(continuation_id).strip())
        if continuation is None:
            raise GoalStoreError(f"unknown continuation_id: {continuation_id}")
        return continuation

    def resume_information_need(
        self,
        *,
        continuation_id: str,
        information_need_id: str,
        resumed_at: str | None = None,
    ) -> ContinuationResumeResult:
        continuation = self.restore(continuation_id)
        need_id = str(information_need_id).strip()
        if (
            continuation.blocked_by_type
            is not ContinuationBlockerType.INFORMATION_NEED
            or continuation.blocked_by_id != need_id
        ):
            raise GoalStoreConflict(
                "continuation is not bound to the supplied InformationNeed"
            )
        need = self._store.get_information_need(need_id)
        if need is None:
            raise GoalStoreError(f"unknown information_need_id: {need_id}")
        if need.state is not InformationNeedState.RESOLVED:
            return ContinuationResumeResult(
                continuation=continuation,
                resumed=False,
                reason="information_need_not_resolved",
            )
        resumed = self._resume(
            continuation,
            resumed_at=resumed_at,
        )
        return ContinuationResumeResult(
            continuation=resumed,
            resumed=True,
            reason="information_need_resolved",
        )

    def resume_verified_blocker(
        self,
        *,
        continuation_id: str,
        blocker_type: ContinuationBlockerType,
        blocker_id: str,
        verifier: BlockerVerifier,
        resumed_at: str | None = None,
    ) -> ContinuationResumeResult:
        if not callable(verifier):
            raise TypeError("verifier must be callable")
        continuation = self.restore(continuation_id)
        blocker_key = str(blocker_id).strip()
        if (
            continuation.blocked_by_type is not blocker_type
            or continuation.blocked_by_id != blocker_key
        ):
            raise GoalStoreConflict(
                "continuation does not match the supplied blocker identity"
            )
        if not verifier(blocker_type, blocker_key):
            return ContinuationResumeResult(
                continuation=continuation,
                resumed=False,
                reason="blocker_not_verified",
            )
        resumed = self._resume(
            continuation,
            resumed_at=resumed_at,
        )
        return ContinuationResumeResult(
            continuation=resumed,
            resumed=True,
            reason="blocker_verified",
        )

    def _resume(
        self,
        continuation: GoalContinuationV1,
        *,
        resumed_at: str | None,
    ) -> GoalContinuationV1:
        if continuation.state is ContinuationState.RESUMED:
            return continuation
        timestamp = resumed_at or datetime.now(UTC).isoformat()
        return self._store.resume_continuation(
            continuation.continuation_id,
            expected_revision=continuation.revision,
            resumed_at=timestamp,
        )
