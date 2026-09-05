from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from .embeddings import (
    JARVIS_MEMORY_RETRIEVAL_INSTRUCTION,
    QWEN3_EMBEDDING_CONTRACT,
    EmbeddingContract,
)
from .retrieval import RetrievalCandidate

QWEN3_RERANKER_MODEL_ID = "Qwen/Qwen3-Reranker-0.6B"
QWEN3_RERANKER_REVISION = "e61197ed45024b0ed8a2d74b80b4d909f1255473"
QWEN3_RERANKER_CANDIDATE_WINDOW = 3


class LocalRetrievalModelError(RuntimeError):
    """Base error for local semantic retrieval model failures."""


class LocalRetrievalDependencyError(LocalRetrievalModelError):
    """Raised when the optional local retrieval dependency set is unavailable."""


class LocalRetrievalOutputError(LocalRetrievalModelError):
    """Raised when a model returns output that violates the production contract."""


class QueryEmbeddingEncoder(Protocol):
    @property
    def contract(self) -> EmbeddingContract:
        """Return the immutable embedding contract implemented by this encoder."""

    def encode_query(self, text: str) -> np.ndarray:
        """Encode one retrieval query as one normalized contract-sized vector."""

    def encode_documents(self, texts: Sequence[str]) -> tuple[np.ndarray, ...]:
        """Encode canonical memory texts as normalized contract-sized vectors."""


class RetrievalReranker(Protocol):
    def rerank(
        self,
        query_text: str,
        candidates: Sequence[RetrievalCandidate],
    ) -> tuple[RerankedCandidate, ...]:
        """Rerank the bounded first-stage candidate window."""


@dataclass(frozen=True, slots=True)
class RerankedCandidate:
    candidate: RetrievalCandidate
    rerank_rank: int
    rerank_score: float


def _text(value: str, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _unit_vector(value: Any, contract: EmbeddingContract) -> np.ndarray:
    try:
        vector = np.asarray(value, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise LocalRetrievalOutputError("embedding output must be numeric") from exc
    if vector.ndim != 1 or vector.shape != (contract.dimension,):
        raise LocalRetrievalOutputError(
            f"embedding output must have shape ({contract.dimension},)"
        )
    if not np.all(np.isfinite(vector)):
        raise LocalRetrievalOutputError("embedding output must contain finite values")
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm <= 0.0:
        raise LocalRetrievalOutputError("embedding output norm must be positive")
    normalized = np.asarray(vector / norm, dtype=np.float32)
    if not np.all(np.isfinite(normalized)):
        raise LocalRetrievalOutputError("normalized embedding contains non-finite values")
    return normalized


def _sentence_transformer_factory() -> Callable[..., Any]:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise LocalRetrievalDependencyError(
            "local retrieval models require the optional 'retrieval' dependency set"
        ) from exc
    return SentenceTransformer


def _cross_encoder_factory() -> Callable[..., Any]:
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise LocalRetrievalDependencyError(
            "local retrieval models require the optional 'retrieval' dependency set"
        ) from exc
    return CrossEncoder


class Qwen3EmbeddingEncoder:
    """Lazy, revision-pinned Qwen3 embedding adapter matching the measured contract."""

    def __init__(
        self,
        *,
        device: str | None = "cuda",
        contract: EmbeddingContract = QWEN3_EMBEDDING_CONTRACT,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        if device is not None and not isinstance(device, str):
            raise TypeError("device must be a string or None")
        self._device = device
        self._contract = contract
        self._model_factory = model_factory
        self._model: Any | None = None
        self._lock = threading.RLock()

    @property
    def contract(self) -> EmbeddingContract:
        return self._contract

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def encode_query(self, text: str) -> np.ndarray:
        query = _text(text, name="query text")
        with self._lock:
            model = self._require_model()
            output = model.encode_query(
                [query],
                prompt=JARVIS_MEMORY_RETRIEVAL_INSTRUCTION,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
                truncate_dim=self._contract.dimension,
            )
        array = np.asarray(output)
        if array.ndim != 2 or array.shape[0] != 1:
            raise LocalRetrievalOutputError(
                "query encoder must return exactly one embedding row"
            )
        return _unit_vector(array[0], self._contract)

    def encode_documents(self, texts: Sequence[str]) -> tuple[np.ndarray, ...]:
        if isinstance(texts, str) or not isinstance(texts, Sequence):
            raise TypeError("document texts must be a sequence of strings")
        normalized = tuple(_text(text, name="document text") for text in texts)
        if not normalized:
            return ()
        with self._lock:
            model = self._require_model()
            output = model.encode_document(
                list(normalized),
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
                truncate_dim=self._contract.dimension,
            )
        array = np.asarray(output)
        if array.ndim != 2 or array.shape[0] != len(normalized):
            raise LocalRetrievalOutputError(
                "document encoder row count does not match requested documents"
            )
        return tuple(_unit_vector(row, self._contract) for row in array)

    def _require_model(self) -> Any:
        if self._model is not None:
            return self._model
        factory = self._model_factory or _sentence_transformer_factory()
        self._model = factory(
            self._contract.model_id,
            revision=self._contract.model_revision,
            device=self._device,
            trust_remote_code=False,
        )
        return self._model


class Qwen3RetrievalReranker:
    """Lazy, top-3 revision-pinned Qwen3 CrossEncoder reranker."""

    def __init__(
        self,
        *,
        device: str | None = "cuda",
        candidate_window: int = QWEN3_RERANKER_CANDIDATE_WINDOW,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        if device is not None and not isinstance(device, str):
            raise TypeError("device must be a string or None")
        if isinstance(candidate_window, bool) or not isinstance(candidate_window, int):
            raise TypeError("candidate_window must be an integer")
        if candidate_window <= 0:
            raise ValueError("candidate_window must be positive")
        self._device = device
        self._candidate_window = candidate_window
        self._model_factory = model_factory
        self._model: Any | None = None
        self._lock = threading.RLock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def candidate_window(self) -> int:
        return self._candidate_window

    def rerank(
        self,
        query_text: str,
        candidates: Sequence[RetrievalCandidate],
    ) -> tuple[RerankedCandidate, ...]:
        query = _text(query_text, name="query text")
        if isinstance(candidates, RetrievalCandidate) or not isinstance(
            candidates, Sequence
        ):
            raise TypeError("candidates must be a sequence of RetrievalCandidate")
        window = tuple(candidates[: self._candidate_window])
        if not window:
            return ()
        if not all(isinstance(candidate, RetrievalCandidate) for candidate in window):
            raise TypeError("candidates must contain only RetrievalCandidate values")

        pairs = [
            (query, candidate.assertion.normalized_text) for candidate in window
        ]
        with self._lock:
            model = self._require_model()
            raw_scores = model.predict(pairs, show_progress_bar=False)
        try:
            scores = np.asarray(raw_scores, dtype=np.float64).reshape(-1)
        except (TypeError, ValueError) as exc:
            raise LocalRetrievalOutputError("reranker scores must be numeric") from exc
        if scores.shape != (len(window),):
            raise LocalRetrievalOutputError(
                "reranker score count does not match candidate count"
            )
        if not np.all(np.isfinite(scores)):
            raise LocalRetrievalOutputError("reranker scores must be finite")

        scored = list(zip(window, scores, strict=True))
        scored.sort(
            key=lambda item: (
                -float(item[1]),
                item[0].fused_rank,
                item[0].assertion.assertion_id,
            )
        )
        return tuple(
            RerankedCandidate(
                candidate=candidate,
                rerank_rank=rank,
                rerank_score=float(score),
            )
            for rank, (candidate, score) in enumerate(scored, start=1)
        )

    def _require_model(self) -> Any:
        if self._model is not None:
            return self._model
        factory = self._model_factory or _cross_encoder_factory()
        self._model = factory(
            QWEN3_RERANKER_MODEL_ID,
            revision=QWEN3_RERANKER_REVISION,
            device=self._device,
            trust_remote_code=False,
        )
        return self._model
