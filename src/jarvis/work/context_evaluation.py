"""C6 quality-equivalence scoring for legacy vs optimized Work context."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.work.brain import BrainDecision


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
