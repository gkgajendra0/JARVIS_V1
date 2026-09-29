"""Advisory EngineeringKnowledge bridge for C6 Work context.

The provider is intentionally optional.  It cannot mint authority and defaults to
the conservative external-context sensitivity policy because Work routing may select
a cloud target.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from jarvis.engineering_knowledge.applicability import ApplicabilityContext
from jarvis.engineering_knowledge.retrieval import (
    EngineeringKnowledgeIndexEncoder,
    EngineeringKnowledgeRetrievalIndex,
    EngineeringKnowledgeRetrievalPolicy,
)
from jarvis.work.models import WorkItem


class EngineeringKnowledgeWorkContextProvider:
    """Project accepted/applicable EngineeringKnowledge into advisory Work evidence."""

    def __init__(
        self,
        index: EngineeringKnowledgeRetrievalIndex,
        *,
        applicability_context_for_work: Callable[
            [WorkItem], ApplicabilityContext | None
        ],
        encoder: EngineeringKnowledgeIndexEncoder | None = None,
        limit: int = 5,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if limit <= 0:
            raise ValueError("EngineeringKnowledge context limit must be positive")
        self._index = index
        self._applicability_context_for_work = applicability_context_for_work
        self._encoder = encoder
        self._limit = int(limit)
        self._clock = clock

    def for_work(self, work: WorkItem) -> tuple[dict[str, Any], ...]:
        context = self._applicability_context_for_work(work)
        if context is None:
            return ()
        candidates = self._index.retrieve(
            work.request,
            context=context,
            encoder=self._encoder,
            policy=EngineeringKnowledgeRetrievalPolicy.external_context(),
            now_epoch=float(self._clock()),
            limit=self._limit,
        )
        return tuple(self._project(candidate) for candidate in candidates)

    @staticmethod
    def _project(candidate) -> dict[str, Any]:
        revision = candidate.revision
        return {
            "kind": "engineering_knowledge",
            "authority": "advisory_only",
            "revision_id": revision.revision_id,
            "knowledge_id": revision.knowledge_id,
            "rank": candidate.rank,
            "summary": revision.normalized_summary,
            "searchable_text": candidate.searchable_text,
            "canonical_digest": revision.canonical_digest,
            "evidence_refs": [
                {
                    "evidence_id": evidence.evidence_id,
                    "relation_type": evidence.relation_type,
                    "canonical_reference": evidence.canonical_reference,
                    "summary": evidence.summary,
                }
                for evidence in candidate.evidence
            ],
        }
