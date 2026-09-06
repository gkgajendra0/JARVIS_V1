"""Provider-independent deterministic release gate for canonical JARVIS memory."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .assertions import SemanticAssertionRecord
from .query_plan import (
    MemoryQueryPlanDisposition,
    MemoryQueryPolicy,
    MemoryQueryProposal,
)
from .retrieval import RetrievalEligibility, SemanticRetrievalService


class MemoryEvidenceDisposition(StrEnum):
    RELEASE = "release"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class TrustedMemoryEvidence:
    """One uniquely resolved, already-eligible canonical current assertion."""

    assertion: SemanticAssertionRecord
    reason_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.assertion, SemanticAssertionRecord):
            raise TypeError("assertion must be a SemanticAssertionRecord")
        if not isinstance(self.reason_code, str):
            raise TypeError("reason_code must be a string")
        reason = self.reason_code.strip()
        if not reason:
            raise ValueError("reason_code must not be empty")
        object.__setattr__(self, "reason_code", reason)


@dataclass(frozen=True, slots=True)
class MemoryEvidenceDecision:
    disposition: MemoryEvidenceDisposition
    reason_code: str
    evidence: TrustedMemoryEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, MemoryEvidenceDisposition):
            raise TypeError("disposition must be a MemoryEvidenceDisposition")
        if not isinstance(self.reason_code, str):
            raise TypeError("reason_code must be a string")
        reason = self.reason_code.strip()
        if not reason:
            raise ValueError("reason_code must not be empty")
        object.__setattr__(self, "reason_code", reason)
        if self.disposition is MemoryEvidenceDisposition.RELEASE:
            if not isinstance(self.evidence, TrustedMemoryEvidence):
                raise ValueError("release decision requires trusted evidence")
        elif self.evidence is not None:
            raise ValueError("abstain decision must not carry trusted evidence")


class MemoryEvidenceGate:
    """JARVIS-owned memory release authority, independent of any brain provider."""

    def __init__(
        self,
        retrieval: SemanticRetrievalService,
        *,
        query_policy: MemoryQueryPolicy | None = None,
    ) -> None:
        if not isinstance(retrieval, SemanticRetrievalService):
            raise TypeError("retrieval must be a SemanticRetrievalService")
        if query_policy is not None and not isinstance(query_policy, MemoryQueryPolicy):
            raise TypeError("query_policy must be a MemoryQueryPolicy when provided")
        self._retrieval = retrieval
        self._query_policy = query_policy or MemoryQueryPolicy()

    async def evaluate(
        self,
        proposal: MemoryQueryProposal,
        *,
        eligibility: RetrievalEligibility | None = None,
    ) -> MemoryEvidenceDecision:
        """Validate one proposal and fail closed unless one exact current fact exists."""

        if not isinstance(proposal, MemoryQueryProposal):
            raise TypeError("proposal must be a MemoryQueryProposal")
        policy = eligibility or RetrievalEligibility.local()
        if not isinstance(policy, RetrievalEligibility):
            raise TypeError("eligibility must be RetrievalEligibility")

        catalog = await self._retrieval.eligible_facet_catalog(eligibility=policy)
        query_decision = self._query_policy.evaluate(proposal, catalog)
        if query_decision.disposition is MemoryQueryPlanDisposition.ABSTAIN:
            return self._abstain(query_decision.reason_code)
        if query_decision.plan is None:
            raise AssertionError("allowed query policy decision is missing its plan")

        records = await self._retrieval.retrieve_exact_current_facet(
            query_decision.plan.facet,
            eligibility=policy,
        )
        if not records:
            return self._abstain("canonical_facet_no_longer_current")
        if len(records) > 1:
            return self._abstain("conflicting_current_assertions")

        assertion = records[0]
        facet = query_decision.plan.facet
        if (
            assertion.subject_scope != facet.subject_scope
            or assertion.subject != facet.subject
            or assertion.predicate != facet.predicate
        ):
            raise AssertionError("exact facet lookup returned a different canonical facet")

        reason = "unique_eligible_current_exact_fact"
        evidence = TrustedMemoryEvidence(assertion=assertion, reason_code=reason)
        return MemoryEvidenceDecision(
            disposition=MemoryEvidenceDisposition.RELEASE,
            reason_code=reason,
            evidence=evidence,
        )

    @staticmethod
    def _abstain(reason_code: str) -> MemoryEvidenceDecision:
        return MemoryEvidenceDecision(
            disposition=MemoryEvidenceDisposition.ABSTAIN,
            reason_code=reason_code,
        )
