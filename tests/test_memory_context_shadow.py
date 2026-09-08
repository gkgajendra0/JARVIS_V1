from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest

from jarvis.conversation import ConversationRole, ConversationTurn
from jarvis.memory.assertions import SemanticAssertionRecord
from jarvis.memory.context_shadow import MemoryContextShadowRuntime
from jarvis.memory.embeddings import QWEN3_EMBEDDING_CONTRACT
from jarvis.memory.query_plan import MemoryFacetCatalog, MemoryFacetKey
from jarvis.memory.retrieval import RetrievalCandidate, RetrievalEligibility
from jarvis.memory.retrieval_models import RerankedCandidate
from jarvis.memory.types import (
    AssertionState,
    FreshnessClass,
    Sensitivity,
    ValueType,
    VerificationState,
)

NOW = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)


def _record(assertion_id: str, text: str) -> SemanticAssertionRecord:
    return SemanticAssertionRecord(
        assertion_id=assertion_id,
        subject_scope="personal",
        subject="owner",
        predicate=f"predicate_{assertion_id}",
        value_type=ValueType.TEXT,
        value=text,
        normalized_text=text,
        source_id=f"source-{assertion_id}",
        valid_from=None,
        valid_to=None,
        system_from=NOW,
        system_to=None,
        last_verified_at=None,
        state=AssertionState.ACTIVE,
        supersedes_id=None,
        verification_state=VerificationState.UNVERIFIED,
        confidence=None,
        freshness_class=FreshnessClass.STABLE,
        sensitivity=Sensitivity.STANDARD,
        created_at=NOW,
        updated_at=NOW,
    )


def _candidate(assertion_id: str, text: str, rank: int) -> RetrievalCandidate:
    return RetrievalCandidate(
        assertion=_record(assertion_id, text),
        fused_rank=rank,
        fused_score=1.0 / (60 + rank),
        lexical_rank=rank,
        lexical_score=-float(rank),
        dense_rank=rank,
        dense_score=1.0 / rank,
    )


class FakeEncoder:
    def __init__(self, *, query_error: Exception | None = None) -> None:
        self.query_error = query_error
        self.query_calls: list[str] = []
        self.document_calls: list[tuple[str, ...]] = []

    @property
    def contract(self):
        return QWEN3_EMBEDDING_CONTRACT

    def encode_query(self, text: str) -> np.ndarray:
        self.query_calls.append(text)
        if self.query_error is not None:
            raise self.query_error
        vector = np.zeros(QWEN3_EMBEDDING_CONTRACT.dimension, dtype=np.float32)
        vector[0] = 1.0
        return vector

    def encode_documents(self, texts) -> tuple[np.ndarray, ...]:
        normalized = tuple(texts)
        self.document_calls.append(normalized)
        vectors = []
        for index, _ in enumerate(normalized):
            vector = np.zeros(QWEN3_EMBEDDING_CONTRACT.dimension, dtype=np.float32)
            vector[index % QWEN3_EMBEDDING_CONTRACT.dimension] = 1.0
            vectors.append(vector)
        return tuple(vectors)


class FakeEmbeddingStore:
    def __init__(self, current_ids: set[str] | None = None) -> None:
        self.current_ids = set(current_ids or set())
        self.is_current_calls: list[tuple[str, str]] = []
        self.upserts: list[tuple[str, str, np.ndarray]] = []

    async def is_current(
        self,
        assertion_id: str,
        *,
        normalized_text: str,
    ) -> bool:
        self.is_current_calls.append((assertion_id, normalized_text))
        return assertion_id in self.current_ids

    async def upsert(
        self,
        assertion_id: str,
        *,
        normalized_text: str,
        vector: np.ndarray,
    ) -> object:
        self.upserts.append((assertion_id, normalized_text, vector))
        self.current_ids.add(assertion_id)
        return object()


class FakeRetrieval:
    def __init__(self, candidates: tuple[RetrievalCandidate, ...]) -> None:
        self.candidates = candidates
        self.catalog_eligibilities: list[RetrievalEligibility | None] = []
        self.exact_calls: list[tuple[MemoryFacetKey, RetrievalEligibility | None]] = []
        self.calls: list[dict[str, Any]] = []

    async def eligible_facet_catalog(
        self,
        *,
        eligibility: RetrievalEligibility | None = None,
    ) -> MemoryFacetCatalog:
        self.catalog_eligibilities.append(eligibility)
        return MemoryFacetCatalog(
            tuple(
                MemoryFacetKey(
                    candidate.assertion.subject_scope,
                    candidate.assertion.subject,
                    candidate.assertion.predicate,
                )
                for candidate in self.candidates
            )
        )

    async def retrieve_exact_current_facet(
        self,
        facet: MemoryFacetKey,
        *,
        eligibility: RetrievalEligibility | None = None,
    ) -> tuple[SemanticAssertionRecord, ...]:
        self.exact_calls.append((facet, eligibility))
        return tuple(
            candidate.assertion
            for candidate in self.candidates
            if (
                candidate.assertion.subject_scope,
                candidate.assertion.subject,
                candidate.assertion.predicate,
            )
            == (facet.subject_scope, facet.subject, facet.predicate)
        )

    async def retrieve_first_stage(
        self,
        query_text: str,
        query_vector,
        *,
        eligibility=None,
        constraints=None,
        limit: int = 3,
    ) -> tuple[RetrievalCandidate, ...]:
        self.calls.append(
            {
                "query_text": query_text,
                "query_vector": query_vector,
                "eligibility": eligibility,
                "constraints": constraints,
                "limit": limit,
            }
        )
        return self.candidates[:limit]


class FakeReranker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[RetrievalCandidate, ...]]] = []

    def rerank(
        self,
        query_text: str,
        candidates,
    ) -> tuple[RerankedCandidate, ...]:
        window = tuple(candidates)
        self.calls.append((query_text, window))
        ranked = tuple(reversed(window))
        return tuple(
            RerankedCandidate(
                candidate=candidate,
                rerank_rank=rank,
                rerank_score=float(len(ranked) - rank + 1),
            )
            for rank, candidate in enumerate(ranked, start=1)
        )


@pytest.mark.asyncio
async def test_shadow_retrieval_observes_only_user_turns_with_cloud_policy() -> None:
    candidates = (
        _candidate("a", "camera: Osmo Pocket 3", 1),
        _candidate("b", "bike: BMW 310 GS", 2),
        _candidate("c", "city: Sagar", 3),
    )
    encoder = FakeEncoder()
    embedding_store = FakeEmbeddingStore()
    retrieval = FakeRetrieval(candidates)
    reranker = FakeReranker()
    runtime = MemoryContextShadowRuntime(
        retrieval=retrieval,
        embedding_store=embedding_store,
        query_encoder=encoder,
        reranker=reranker,
    )

    runtime.observe_turn(
        ConversationTurn(role=ConversationRole.ASSISTANT, text="What would you like?")
    )
    assert runtime.pending_task_count == 0

    turn = ConversationTurn(
        role=ConversationRole.USER,
        text="Which camera gives Jarvis eyes?",
    )
    runtime.observe_turn(turn)
    await runtime.wait_idle()

    cloud_policy = RetrievalEligibility.cloud_context()
    assert retrieval.catalog_eligibilities == [cloud_policy]
    assert len(retrieval.exact_calls) == 3
    assert all(eligibility == cloud_policy for _, eligibility in retrieval.exact_calls)
    assert encoder.document_calls == [
        ("camera: Osmo Pocket 3", "bike: BMW 310 GS", "city: Sagar")
    ]
    assert [item[0] for item in embedding_store.upserts] == ["a", "b", "c"]
    assert encoder.query_calls == [turn.text]
    assert len(retrieval.calls) == 1
    call = retrieval.calls[0]
    assert call["query_text"] == turn.text
    assert call["eligibility"] == cloud_policy
    assert call["constraints"] is None
    assert call["limit"] == 3
    assert len(reranker.calls) == 1

    observations = runtime.observations
    assert len(observations) == 1
    assert observations[0].turn_id == turn.turn_id
    assert observations[0].assertion_ids == ("c", "b", "a")
    assert observations[0].indexed_embeddings == 3
    assert observations[0].latency_ms >= 0.0
    assert runtime.closed is False


@pytest.mark.asyncio
async def test_shadow_reuses_current_derived_vectors_without_document_reencoding() -> (
    None
):
    candidates = (_candidate("a", "alpha", 1),)
    encoder = FakeEncoder()
    embedding_store = FakeEmbeddingStore({"a"})
    runtime = MemoryContextShadowRuntime(
        retrieval=FakeRetrieval(candidates),
        embedding_store=embedding_store,
        query_encoder=encoder,
        reranker=FakeReranker(),
    )

    runtime.observe_turn(
        ConversationTurn(role=ConversationRole.USER, text="Recall alpha")
    )
    await runtime.wait_idle()

    assert encoder.document_calls == []
    assert embedding_store.upserts == []
    assert runtime.observations[0].indexed_embeddings == 0


@pytest.mark.asyncio
async def test_shadow_model_failure_isolated_from_conversation_and_context() -> None:
    runtime = MemoryContextShadowRuntime(
        retrieval=FakeRetrieval((_candidate("a", "alpha", 1),)),
        embedding_store=FakeEmbeddingStore({"a"}),
        query_encoder=FakeEncoder(query_error=RuntimeError("model unavailable")),
        reranker=FakeReranker(),
    )
    turn = ConversationTurn(role=ConversationRole.USER, text="Recall alpha")

    runtime.observe_turn(turn)
    await runtime.wait_idle()

    assert runtime.observations == ()
    assert runtime.pending_task_count == 0
    assert runtime.closed is False


@pytest.mark.asyncio
async def test_shadow_close_disposes_session_evidence_and_blocks_new_work() -> None:
    runtime = MemoryContextShadowRuntime(
        retrieval=FakeRetrieval((_candidate("a", "alpha", 1),)),
        embedding_store=FakeEmbeddingStore({"a"}),
        query_encoder=FakeEncoder(),
        reranker=FakeReranker(),
    )
    turn = ConversationTurn(role=ConversationRole.USER, text="Recall alpha")
    runtime.observe_turn(turn)
    await runtime.wait_idle()
    assert len(runtime.observations) == 1

    runtime.close()

    assert runtime.closed is True
    assert runtime.observations == ()
    assert runtime.pending_task_count == 0

    runtime.observe_turn(
        ConversationTurn(role=ConversationRole.USER, text="This must be ignored")
    )
    assert runtime.pending_task_count == 0
