"""Bounded provider-assisted semantic release after deterministic memory gates."""

from __future__ import annotations

import logging

from .evidence_gate import (
    MemoryEvidenceDecision,
    MemoryEvidenceDisposition,
    TrustedMemoryEvidence,
)
from .query_coordinator import MemoryQueryCoordinator
from .release_guard import MemoryReleaseGuard, MemoryReleaseJudgement
from .retrieval import RetrievalEligibility
from .types import Sensitivity

LOGGER = logging.getLogger(__name__)


class ProviderVerifiedMemoryQueryCoordinator:
    """Fail closed unless deterministic core and same-provider verifier both allow."""

    def __init__(
        self,
        *,
        coordinator: MemoryQueryCoordinator,
        release_guard: MemoryReleaseGuard,
    ) -> None:
        if not isinstance(coordinator, MemoryQueryCoordinator):
            raise TypeError("coordinator must be a MemoryQueryCoordinator")
        if not callable(getattr(release_guard, "evaluate", None)):
            raise TypeError("release_guard must implement MemoryReleaseGuard")
        self._coordinator = coordinator
        self._release_guard = release_guard

    @property
    def provider_name(self) -> str:
        return self._release_guard.provider_name

    @property
    def model_name(self) -> str:
        return self._release_guard.model_name

    async def resolve(
        self,
        text: str,
        *,
        eligibility: RetrievalEligibility | None = None,
    ) -> MemoryEvidenceDecision:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        query_text = text.strip()
        if not query_text:
            raise ValueError("text must not be empty")

        policy = eligibility or RetrievalEligibility.cloud_context()
        if not isinstance(policy, RetrievalEligibility):
            raise TypeError("eligibility must be RetrievalEligibility")
        if Sensitivity.LOCAL_ONLY in policy.sensitivities:
            return self._abstain(
                "provider_semantic_recall_requires_cloud_safe_eligibility"
            )

        try:
            core = await self._coordinator.resolve(query_text, eligibility=policy)
        except Exception:
            LOGGER.exception("Memory query core failed; semantic recall is abstaining")
            return self._abstain("memory_query_core_unavailable")

        if not isinstance(core, MemoryEvidenceDecision):
            LOGGER.error("Memory query core returned an invalid decision type")
            return self._abstain("memory_query_core_invalid_decision")
        if core.disposition is MemoryEvidenceDisposition.ABSTAIN:
            return core
        if core.evidence is None:
            LOGGER.error("Memory query core released without evidence")
            return self._abstain("memory_query_core_missing_evidence")

        try:
            judgement = await self._release_guard.evaluate(
                text=query_text,
                evidence=core.evidence.assertion,
            )
        except Exception:
            LOGGER.exception("Provider memory-release verifier failed; abstaining")
            return self._abstain("provider_memory_release_guard_unavailable")

        if not isinstance(judgement, MemoryReleaseJudgement):
            LOGGER.error("Provider memory-release verifier returned an invalid type")
            return self._abstain("provider_memory_release_guard_invalid_decision")
        if not judgement.allows_release:
            return self._abstain(
                f"provider_memory_release_veto_{judgement.answer_type.value}"
            )

        reason = "provider_verified_unique_eligible_current_exact_fact"
        return MemoryEvidenceDecision(
            disposition=MemoryEvidenceDisposition.RELEASE,
            reason_code=reason,
            evidence=TrustedMemoryEvidence(
                assertion=core.evidence.assertion,
                reason_code=reason,
            ),
        )

    @staticmethod
    def _abstain(reason_code: str) -> MemoryEvidenceDecision:
        return MemoryEvidenceDecision(
            disposition=MemoryEvidenceDisposition.ABSTAIN,
            reason_code=reason_code,
        )
