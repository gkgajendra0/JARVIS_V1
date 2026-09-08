"""Fail-closed composition of semantic veto and deterministic memory evidence."""

from __future__ import annotations

import logging

from .answer_type_guard import MemoryAnswerTypeDecision, MemoryAnswerTypeGuard
from .evidence_gate import (
    MemoryEvidenceDecision,
    MemoryEvidenceDisposition,
)
from .query_coordinator import MemoryQueryCoordinator
from .retrieval import RetrievalEligibility

logger = logging.getLogger(__name__)


class GuardedMemoryQueryCoordinator:
    """Only release when the local semantic veto and JARVIS core both allow."""

    def __init__(
        self,
        *,
        coordinator: MemoryQueryCoordinator,
        answer_type_guard: MemoryAnswerTypeGuard,
    ) -> None:
        if not isinstance(coordinator, MemoryQueryCoordinator):
            raise TypeError("coordinator must be a MemoryQueryCoordinator")
        if not callable(getattr(answer_type_guard, "evaluate", None)):
            raise TypeError("answer_type_guard must implement MemoryAnswerTypeGuard")
        self._coordinator = coordinator
        self._answer_type_guard = answer_type_guard

    async def resolve(
        self,
        text: str,
        *,
        eligibility: RetrievalEligibility | None = None,
    ) -> MemoryEvidenceDecision:
        """Apply the local veto before the provider-neutral deterministic core."""

        if not isinstance(text, str):
            raise TypeError("text must be a string")
        query_text = text.strip()
        if not query_text:
            raise ValueError("text must not be empty")

        try:
            guard_decision = await self._answer_type_guard.evaluate(query_text)
        except Exception:
            logger.exception("Memory answer-type guard failed; abstaining")
            return self._abstain("answer_type_guard_unavailable")

        if not isinstance(guard_decision, MemoryAnswerTypeDecision):
            logger.error("Memory answer-type guard returned an invalid decision type")
            return self._abstain("answer_type_guard_invalid_decision")
        if not guard_decision.allow:
            return self._abstain(f"answer_type_veto_{guard_decision.answer_type.value}")

        return await self._coordinator.resolve(
            query_text,
            eligibility=eligibility,
        )

    @staticmethod
    def _abstain(reason_code: str) -> MemoryEvidenceDecision:
        return MemoryEvidenceDecision(
            disposition=MemoryEvidenceDisposition.ABSTAIN,
            reason_code=reason_code,
        )
