"""C6 quality-equivalence scoring for legacy vs optimized Work context."""

from __future__ import annotations

from dataclasses import dataclass, replace

from jarvis.brain_routing.models import BrainRouteRecord
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.work.brain import BrainAction, BrainDecision, BrainRequest
from jarvis.work.context import WorkContextAssembler, WorkContextMode
from jarvis.work.models import WorkItem, WorkState, WorkStep


@dataclass(frozen=True, slots=True)
class ContextDecisionEquivalence:
    action_equal: bool
    goal_complete_equal: bool
    needs_owner_equal: bool
    owner_question_equal: bool
    parameters_equal: bool

    @property
    def equivalent(self) -> bool:
        return (
            self.action_equal
            and self.goal_complete_equal
            and self.needs_owner_equal
            and self.owner_question_equal
            and self.parameters_equal
        )


def compare_context_decisions(
    legacy: BrainDecision,
    optimized: BrainDecision,
) -> ContextDecisionEquivalence:
    """Score the decision fields C6 must preserve before apply rollout."""

    return ContextDecisionEquivalence(
        action_equal=legacy.action == optimized.action,
        goal_complete_equal=legacy.goal_complete == optimized.goal_complete,
        needs_owner_equal=legacy.needs_owner == optimized.needs_owner,
        owner_question_equal=legacy.owner_question == optimized.owner_question,
        parameters_equal=legacy.parameters == optimized.parameters,
    )


def compare_recorded_context_decision(
    recorded: BrainRouteRecord,
    optimized: BrainDecision,
) -> ContextDecisionEquivalence | None:
    """Compare an optimized replay with one durably recorded legacy decision.

    Older BrainRouteRecord rows predate C6 decision provenance. Returning None keeps
    those rows explicitly non-comparable rather than treating missing fields as a
    successful equivalence result.
    """

    if not isinstance(recorded, BrainRouteRecord):
        raise TypeError("recorded must be a BrainRouteRecord")
    if not isinstance(optimized, BrainDecision):
        raise TypeError("optimized must be a BrainDecision")
    if (
        recorded.goal_complete is None
        or recorded.needs_owner is None
        or recorded.parameters_digest is None
    ):
        return None

    return ContextDecisionEquivalence(
        action_equal=recorded.selected_action == optimized.action,
        goal_complete_equal=recorded.goal_complete == optimized.goal_complete,
        needs_owner_equal=recorded.needs_owner == optimized.needs_owner,
        owner_question_equal=recorded.owner_question == optimized.owner_question,
        parameters_equal=(
            recorded.parameters_digest == canonical_digest(optimized.parameters)
        ),
    )


def reconstruct_recorded_context_request(
    *,
    snapshot: dict[str, object],
    work: WorkItem,
    steps: tuple[WorkStep, ...],
    assembler: WorkContextAssembler | None = None,
) -> BrainRequest:
    """Rebuild one historical SHADOW reasoning cycle as an APPLY replay request."""

    if snapshot.get("schema") != "c6_work_reasoning_snapshot.v1":
        raise ValueError("unsupported C6 work reasoning snapshot schema")
    if not isinstance(work, WorkItem):
        raise TypeError("work must be a WorkItem")
    if any(not isinstance(step, WorkStep) for step in steps):
        raise TypeError("steps must contain WorkStep values")

    history_count = snapshot.get("history_step_count")
    if isinstance(history_count, bool) or not isinstance(history_count, int):
        raise TypeError("history_step_count must be an integer")
    if history_count < 0 or history_count > len(steps):
        raise ValueError("C6 replay history prefix is unavailable")
    history = tuple(steps[:history_count])
    expected_history_digest = str(
        snapshot.get("history_step_ids_digest") or ""
    ).strip().casefold()
    actual_history_digest = canonical_digest([step.step_id for step in history])
    if expected_history_digest != actual_history_digest:
        raise ValueError("C6 replay history prefix differs from durable provenance")

    recent_ids_raw = snapshot.get("recent_step_ids")
    if not isinstance(recent_ids_raw, list):
        raise TypeError("recent_step_ids must be an array")
    recent_ids = tuple(str(item).strip() for item in recent_ids_raw)
    if any(not item for item in recent_ids):
        raise ValueError("recent_step_ids must not contain empty values")
    step_by_id = {step.step_id: step for step in history}
    if any(step_id not in step_by_id for step_id in recent_ids):
        raise ValueError("C6 replay recent step is outside the durable history prefix")
    recent_steps = tuple(step_by_id[step_id] for step_id in recent_ids)

    actions_raw = snapshot.get("allowed_actions")
    if not isinstance(actions_raw, list) or not actions_raw:
        raise ValueError("C6 replay requires the historical action catalog")
    actions: list[BrainAction] = []
    for item in actions_raw:
        if not isinstance(item, dict):
            raise TypeError("C6 replay action entries must be objects")
        schema = item.get("parameter_schema")
        if not isinstance(schema, dict):
            raise TypeError("C6 replay action schema must be an object")
        actions.append(
            BrainAction(
                name=str(item.get("name") or ""),
                description=str(item.get("description") or ""),
                parameter_schema=dict(schema),
            )
        )

    evidence_raw = snapshot.get("evidence")
    if not isinstance(evidence_raw, list):
        raise TypeError("C6 replay evidence must be an array")
    evidence: list[dict[str, object]] = []
    for item in evidence_raw:
        if not isinstance(item, dict):
            raise TypeError("C6 replay evidence entries must be objects")
        evidence.append(dict(item))

    work_version = snapshot.get("work_version")
    if isinstance(work_version, bool) or not isinstance(work_version, int):
        raise TypeError("C6 replay work_version must be an integer")
    if work_version <= 0:
        raise ValueError("C6 replay work_version must be positive")
    work_state = WorkState(str(snapshot.get("work_state") or ""))
    raw_status = snapshot.get("work_status_detail")
    status_detail = None if raw_status is None else str(raw_status)
    historical_work = replace(
        work,
        state=work_state,
        status_detail=status_detail,
        version=work_version,
    )

    purpose = str(snapshot.get("purpose") or "").strip()
    if not purpose:
        raise ValueError("C6 replay purpose must not be empty")
    context_pack = (assembler or WorkContextAssembler()).build(
        work=historical_work,
        steps=history,
        evidence=tuple(evidence),
    )
    return BrainRequest(
        work=historical_work,
        recent_steps=recent_steps,
        purpose=purpose,
        allowed_actions=tuple(actions),
        evidence=tuple(evidence),
        context_pack=context_pack,
        context_mode=WorkContextMode.APPLY,
    )

