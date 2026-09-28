"""Integrity adapter for accepted Phase-10 engineering-learning revisions."""

from __future__ import annotations

from jarvis.engineering_knowledge.security import EngineeringKnowledgeIntegrityDecision

from .lifecycle import (
    EngineeringLearningLifecycleStore,
    EngineeringLearningPromotionPolicy,
)


class EngineeringLearningIntegrityVerifier:
    """Reuse the stricter promotion policy as the retrieval integrity boundary."""

    def __init__(
        self,
        *,
        policy: EngineeringLearningPromotionPolicy | None = None,
    ) -> None:
        self._policy = policy or EngineeringLearningPromotionPolicy()

    def verify(
        self,
        store: EngineeringLearningLifecycleStore,
        revision_id: str,
    ) -> EngineeringKnowledgeIntegrityDecision:
        assessment = self._policy.evaluate(store, revision_id)
        return EngineeringKnowledgeIntegrityDecision(
            valid=assessment.decision.eligible,
            reason_codes=assessment.decision.reason_codes,
        )
