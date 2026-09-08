"""Provider-neutral orchestration from user query to deterministic memory evidence."""

from __future__ import annotations

from .evidence_gate import (
    MemoryEvidenceDecision,
    MemoryEvidenceDisposition,
    MemoryEvidenceGate,
)
from .query_grounding import (
    MemoryQueryGroundingDisposition,
    MemoryQueryGroundingPolicy,
)
from .query_plan import MemoryQueryInterpreter, MemoryQueryProposal
from .retrieval import RetrievalEligibility, SemanticRetrievalService


class MemoryQueryCoordinator:
    """Treat interpreter output as untrusted input before memory release."""

    def __init__(
        self,
        *,
        interpreter: MemoryQueryInterpreter,
        retrieval: SemanticRetrievalService,
        grounding_policy: MemoryQueryGroundingPolicy | None = None,
    ) -> None:
        if not callable(getattr(interpreter, "interpret", None)):
            raise TypeError("interpreter must implement MemoryQueryInterpreter")
        if not isinstance(retrieval, SemanticRetrievalService):
            raise TypeError("retrieval must be a SemanticRetrievalService")
        if grounding_policy is not None and not isinstance(
            grounding_policy,
            MemoryQueryGroundingPolicy,
        ):
            raise TypeError(
                "grounding_policy must be a MemoryQueryGroundingPolicy when provided"
            )
        self._interpreter = interpreter
        self._retrieval = retrieval
        self._grounding_policy = grounding_policy or MemoryQueryGroundingPolicy()
        self._evidence_gate = MemoryEvidenceGate(retrieval)

    async def resolve(
        self,
        text: str,
        *,
        eligibility: RetrievalEligibility | None = None,
    ) -> MemoryEvidenceDecision:
        """Resolve one natural-language query without granting the interpreter authority."""

        if not isinstance(text, str):
            raise TypeError("text must be a string")
        query_text = text.strip()
        if not query_text:
            raise ValueError("text must not be empty")
        policy = eligibility or RetrievalEligibility.local()
        if not isinstance(policy, RetrievalEligibility):
            raise TypeError("eligibility must be RetrievalEligibility")

        catalog = await self._retrieval.eligible_facet_catalog(eligibility=policy)
        proposal = await self._interpreter.interpret(
            text=query_text,
            catalog=catalog,
        )
        if not isinstance(proposal, MemoryQueryProposal):
            raise TypeError("interpreter returned an invalid proposal type")

        grounding = self._grounding_policy.evaluate(
            text=query_text,
            proposal=proposal,
            catalog=catalog,
        )
        if grounding.disposition is MemoryQueryGroundingDisposition.ABSTAIN:
            return MemoryEvidenceDecision(
                disposition=MemoryEvidenceDisposition.ABSTAIN,
                reason_code=grounding.reason_code,
            )

        return await self._evidence_gate.evaluate(
            proposal,
            eligibility=policy,
        )
