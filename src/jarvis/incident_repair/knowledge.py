"""Accepted EngineeringKnowledge retrieval for Phase-6 incident diagnosis."""

from __future__ import annotations

from jarvis.engineering_knowledge.applicability import (
    ApplicabilityContext,
    ApplicabilityFact,
)
from jarvis.engineering_knowledge.retrieval import (
    EngineeringKnowledgeRetrievalIndex,
    EngineeringKnowledgeRetrievalPolicy,
)

from .evidence import IncidentEvidencePackage


class IncidentKnowledgeRetriever:
    """Retrieve only accepted/current/integrity-valid knowledge for incident context."""

    def __init__(
        self,
        index: EngineeringKnowledgeRetrievalIndex,
        *,
        limit: int = 5,
    ) -> None:
        if not isinstance(index, EngineeringKnowledgeRetrievalIndex):
            raise TypeError("index must be EngineeringKnowledgeRetrievalIndex")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        self._index = index
        self._limit = limit

    def retrieve_revision_ids(
        self,
        package: IncidentEvidencePackage,
        *,
        now_epoch: float,
    ) -> tuple[str, ...]:
        if not isinstance(package, IncidentEvidencePackage):
            raise TypeError("package must be IncidentEvidencePackage")
        facts = tuple(
            ApplicabilityFact(
                target_namespace="jarvis.component",
                target_identity=component_id,
                attributes={},
            )
            for component_id in package.affected_components
        )
        if not facts:
            return ()

        query_parts = [
            package.title,
            package.symptom,
            *package.affected_components,
        ]
        query = " ".join(
            part.strip()
            for part in query_parts
            if part.strip() and not part.startswith("[BLOCKED_")
        )
        if not query:
            return ()

        candidates = self._index.retrieve(
            query,
            context=ApplicabilityContext(facts=facts),
            encoder=None,
            policy=EngineeringKnowledgeRetrievalPolicy.local(),
            now_epoch=now_epoch,
            limit=self._limit,
        )
        return tuple(candidate.revision.revision_id for candidate in candidates)
