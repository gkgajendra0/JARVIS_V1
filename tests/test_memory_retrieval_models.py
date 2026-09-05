from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest

from jarvis.memory.assertions import SemanticAssertionRecord
from jarvis.memory.embeddings import (
    JARVIS_MEMORY_RETRIEVAL_INSTRUCTION,
    QWEN3_EMBEDDING_CONTRACT,
)
from jarvis.memory.retrieval import RetrievalCandidate
from jarvis.memory.retrieval_models import (
    QWEN3_RERANKER_MODEL_ID,
    QWEN3_RERANKER_REVISION,
    LocalRetrievalOutputError,
    Qwen3EmbeddingEncoder,
    Qwen3RetrievalReranker,
)
from jarvis.memory.types import (
    AssertionState,
    FreshnessClass,
    Sensitivity,
    ValueType,
    VerificationState,
)

NOW = datetime(2026, 9, 5, 19, 0, tzinfo=UTC)


def vector(index: int, scale: float = 1.0) -> np.ndarray:
    output = np.zeros(QWEN3_EMBEDDING_CONTRACT.dimension, dtype=np.float32)
    output[index] = scale
    return output


def record(assertion_id: str, text: str) -> SemanticAssertionRecord:
    return SemanticAssertionRecord(
        assertion_id=assertion_id,
        subject_scope="owner",
        subject="owner",
        predicate="test_memory",
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


def candidate(assertion_id: str, text: str, rank: int) -> RetrievalCandidate:
    return RetrievalCandidate(
        assertion=record(assertion_id, text),
        fused_rank=rank,
        fused_score=1.0 / (60 + rank),
        lexical_rank=rank,
        lexical_score=-float(rank),
        dense_rank=rank,
        dense_score=1.0 / rank,
    )


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.query_calls: list[tuple[list[str], dict[str, Any]]] = []
        self.document_calls: list[tuple[list[str], dict[str, Any]]] = []

    def encode_query(self, texts: list[str], **kwargs: Any) -> np.ndarray:
        self.query_calls.append((texts, kwargs))
        return np.asarray([vector(0, 4.0)])

    def encode_document(self, texts: list[str], **kwargs: Any) -> np.ndarray:
        self.document_calls.append((texts, kwargs))
        return np.asarray(
            [vector(index, float(index + 2)) for index in range(len(texts))]
        )


class FakeRerankerModel:
    def __init__(self, scores: list[float]) -> None:
        self._scores = scores
        self.calls: list[tuple[list[tuple[str, str]], dict[str, Any]]] = []

    def predict(self, pairs: list[tuple[str, str]], **kwargs: Any) -> np.ndarray:
        self.calls.append((pairs, kwargs))
        return np.asarray(self._scores, dtype=np.float64)


def test_embedding_adapter_is_lazy_revision_pinned_and_matches_measured_contract() -> (
    None
):
    created: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    model = FakeEmbeddingModel()

    def factory(*args: Any, **kwargs: Any) -> FakeEmbeddingModel:
        created.append((args, kwargs))
        return model

    encoder = Qwen3EmbeddingEncoder(model_factory=factory)
    assert encoder.loaded is False

    query = encoder.encode_query("Which camera gives Jarvis eyes?")

    assert encoder.loaded is True
    assert len(created) == 1
    args, kwargs = created[0]
    assert args == (QWEN3_EMBEDDING_CONTRACT.model_id,)
    assert kwargs == {
        "revision": QWEN3_EMBEDDING_CONTRACT.model_revision,
        "device": "cuda",
        "trust_remote_code": False,
    }
    assert query.shape == (QWEN3_EMBEDDING_CONTRACT.dimension,)
    assert np.linalg.norm(query) == pytest.approx(1.0)

    texts, encode_kwargs = model.query_calls[0]
    assert texts == ["Which camera gives Jarvis eyes?"]
    assert encode_kwargs["prompt"] == JARVIS_MEMORY_RETRIEVAL_INSTRUCTION
    assert encode_kwargs["normalize_embeddings"] is True
    assert encode_kwargs["convert_to_numpy"] is True
    assert encode_kwargs["show_progress_bar"] is False
    assert encode_kwargs["truncate_dim"] == QWEN3_EMBEDDING_CONTRACT.dimension


def test_embedding_adapter_documents_are_normalized_and_empty_batch_stays_lazy() -> (
    None
):
    model = FakeEmbeddingModel()
    calls = 0

    def factory(*args: Any, **kwargs: Any) -> FakeEmbeddingModel:
        nonlocal calls
        calls += 1
        return model

    encoder = Qwen3EmbeddingEncoder(model_factory=factory)
    assert encoder.encode_documents([]) == ()
    assert calls == 0

    documents = encoder.encode_documents(["alpha", "beta"])

    assert calls == 1
    assert len(documents) == 2
    assert all(np.linalg.norm(document) == pytest.approx(1.0) for document in documents)
    texts, encode_kwargs = model.document_calls[0]
    assert texts == ["alpha", "beta"]
    assert "prompt" not in encode_kwargs
    assert encode_kwargs["truncate_dim"] == QWEN3_EMBEDDING_CONTRACT.dimension


def test_embedding_adapter_rejects_wrong_model_output_shape() -> None:
    class BadModel(FakeEmbeddingModel):
        def encode_query(self, texts: list[str], **kwargs: Any) -> np.ndarray:
            return np.zeros((2, QWEN3_EMBEDDING_CONTRACT.dimension), dtype=np.float32)

    encoder = Qwen3EmbeddingEncoder(model_factory=lambda *args, **kwargs: BadModel())

    with pytest.raises(LocalRetrievalOutputError, match="exactly one"):
        encoder.encode_query("query")


def test_reranker_is_lazy_top3_revision_pinned_and_preserves_first_stage_ties() -> None:
    created: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    model = FakeRerankerModel([0.5, 0.5, 0.7])

    def factory(*args: Any, **kwargs: Any) -> FakeRerankerModel:
        created.append((args, kwargs))
        return model

    reranker = Qwen3RetrievalReranker(model_factory=factory)
    inputs = [
        candidate("a", "alpha", 1),
        candidate("b", "beta", 2),
        candidate("c", "gamma", 3),
        candidate("d", "delta", 4),
    ]
    assert reranker.loaded is False

    ranked = reranker.rerank("memory query", inputs)

    assert reranker.loaded is True
    assert len(created) == 1
    args, kwargs = created[0]
    assert args == (QWEN3_RERANKER_MODEL_ID,)
    assert kwargs == {
        "revision": QWEN3_RERANKER_REVISION,
        "device": "cuda",
        "trust_remote_code": False,
    }
    assert [item.candidate.assertion.assertion_id for item in ranked] == ["c", "a", "b"]
    assert [item.rerank_rank for item in ranked] == [1, 2, 3]
    assert [item.rerank_score for item in ranked] == pytest.approx([0.7, 0.5, 0.5])

    pairs, predict_kwargs = model.calls[0]
    assert pairs == [
        ("memory query", "alpha"),
        ("memory query", "beta"),
        ("memory query", "gamma"),
    ]
    assert predict_kwargs == {"show_progress_bar": False}


def test_reranker_rejects_nonfinite_scores() -> None:
    model = FakeRerankerModel([float("nan")])
    reranker = Qwen3RetrievalReranker(model_factory=lambda *args, **kwargs: model)

    with pytest.raises(LocalRetrievalOutputError, match="finite"):
        reranker.rerank("query", [candidate("a", "alpha", 1)])
