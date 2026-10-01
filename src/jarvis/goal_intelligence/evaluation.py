"""Observation evaluation, bounded replanning and stagnation controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .models import OwnerGoalV2, PlanGraphV1
from .planning import GoalPlanner, PlanValidationContext
from .store import GoalStore, GoalStoreConflict


@dataclass(frozen=True, slots=True)
class ReplanResult:
    previous_plan_id: str
    previous_plan_revision: int
    replacement: PlanGraphV1
    attempt: int


class ReplanController:
    """Bound model replanning while keeping old plan revisions auditable."""

    def __init__(
        self,
        *,
        store: GoalStore,
        planner: GoalPlanner,
        max_replans: int = 3,
    ) -> None:
        if not isinstance(store, GoalStore):
            raise TypeError("store must be GoalStore")
        if not isinstance(planner, GoalPlanner):
            raise TypeError("planner must be GoalPlanner")
        if isinstance(max_replans, bool) or not isinstance(max_replans, int):
            raise TypeError("max_replans must be an integer")
        if not 1 <= max_replans <= 10:
            raise ValueError("max_replans must be between 1 and 10")
        self._store = store
        self._planner = planner
        self._max_replans = max_replans

    async def replan(
        self,
        *,
        goal: OwnerGoalV2,
        failed_plan: PlanGraphV1,
        context: PlanValidationContext,
        prior_evidence: tuple[str, ...] | list[str],
    ) -> ReplanResult:
        if failed_plan.goal_id != goal.goal_id:
            raise ValueError("failed plan does not belong to owner goal")
        attempt = self._store.consume_replan_budget(
            goal_id=goal.goal_id,
            max_attempts=self._max_replans,
            updated_at=datetime.now(UTC).isoformat(),
        )
        replacement = await self._planner.plan(
            goal=goal,
            context=context,
            prior_evidence=prior_evidence,
            plan_revision=failed_plan.plan_revision + 1,
        )
        if replacement.plan_id == failed_plan.plan_id:
            raise GoalStoreConflict("replan must create a new plan revision")
        replacement = self._store.put_plan(replacement)
        return ReplanResult(
            previous_plan_id=failed_plan.plan_id,
            previous_plan_revision=failed_plan.plan_revision,
            replacement=replacement,
            attempt=attempt,
        )


def stagnation_reason(
    *,
    action_fingerprint: str,
    state_fingerprint: str,
) -> str:
    action = str(action_fingerprint).strip().casefold()
    state = str(state_fingerprint).strip().casefold()
    if not action or not state:
        raise ValueError("stagnation fingerprints must not be empty")
    return f"repeated_action_without_progress:action={action[:16]}:state={state[:16]}"
