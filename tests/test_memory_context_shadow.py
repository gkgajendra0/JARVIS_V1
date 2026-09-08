from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest

from jarvis.conversation import ConversationRole, ConversationTurn
from jarvis.memory.assertions import SemanticAssertionRecord
from jarvis.memory.context_shadow import MemoryContextShadowRuntime
from jarvis.memory.embeddings import QWEN3_EMBEDDING_CONTRACT
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
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[str] = []

    @property
    def contract(self):
        return QWEN3_EMBEDDING_CONTRACT

    def encode_query(self, text: str) -> np.ndarray:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        vector = np.zeros(QWEN3_EMBEDDING_CONTRACT.dimension, dtype=np.float32)
        vector[0] = 1.0
        return vector

    def encode_documents(self, texts):
        del texts
        raise AssertionError("shadow runtime must never encode documents")


class FakeRetrieval:
    def __init__(self, candidates: tuple[RetrievalCandidate, ...]) -> None:
        self.candidates = candidates
        self.calls: list[dict[str, Any]] = []

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
async def test_shadow_retrieval_observes_only_accepted_user_turns_with_cloud_policy() -> (
    None
):
    candidates = (
        _candidate("a", "camera: Osmo Pocket 3", 1),
        _candidate("b", "bike: BMW 310 GS", 2),
        _candidate("c", "city: Sagar", 3),
    )
    encoder = FakeEncoder()
    retrieval = FakeRetrieval(candidates)
    reranker = FakeReranker()
    runtime = MemoryContextShadowRuntime(
        retrieval=retrieval,
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

    assert encoder.calls == [turn.text]
    assert len(retrieval.calls) == 1
    call = retrieval.calls[0]
    assert call["query_text"] == turn.text
    assert call["eligibility"] == RetrievalEligibility.cloud_context()
    assert call["constraints"] is None
    assert call["limit"] == 3
    assert len(reranker.calls) == 1

    observations = runtime.observations
    assert len(observations) == 1
    assert observations[0].turn_id == turn.turn_id
    assert observations[0].assertion_ids == ("c", "b", "a")
    assert observations[0].latency_ms >= 0.0
    assert runtime.closed is False


@pytest.mark.asyncio
async def test_shadow_model_failure_isolated_from_conversation_and_context() -> None:
    runtime = MemoryContextShadowRuntime(
        retrieval=FakeRetrieval((_candidate("a", "alpha", 1),)),
        query_encoder=FakeEncoder(error=RuntimeError("model unavailable")),
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
