"""Shadow-only semantic memory retrieval for Phase 4.5E measurement.

This runtime observes already-accepted canonical USER turns and measures the
existing local retrieval stack without mutating conversation state, provider
context, or durable memory.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from jarvis.conversation import ConversationRole, ConversationTurn

from .retrieval import RetrievalCandidate, RetrievalEligibility
from .retrieval_models import (
    QueryEmbeddingEncoder,
    RerankedCandidate,
    RetrievalReranker,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_CANDIDATE_LIMIT = 3
DEFAULT_MAX_OBSERVATIONS = 64


class FirstStageMemoryRetriever(Protocol):
    async def retrieve_first_stage(
        self,
        query_text: str,
        query_vector: np.ndarray | list[float] | tuple[float, ...],
        *,
        eligibility: RetrievalEligibility | None = None,
        constraints: object | None = None,
        limit: int = 3,
    ) -> tuple[RetrievalCandidate, ...]:
        """Return already-eligible first-stage retrieval candidates."""


@dataclass(frozen=True, slots=True)
class MemoryContextShadowObservation:
    """Session-local diagnostic evidence for one accepted USER turn."""

    turn_id: str
    reranked_candidates: tuple[RerankedCandidate, ...]
    latency_ms: float

    @property
    def assertion_ids(self) -> tuple[str, ...]:
        return tuple(
            item.candidate.assertion.assertion_id for item in self.reranked_candidates
        )


class MemoryContextShadowRuntime:
    """Measure semantic memory candidates without granting context authority."""

    def __init__(
        self,
        *,
        retrieval: FirstStageMemoryRetriever,
        query_encoder: QueryEmbeddingEncoder,
        reranker: RetrievalReranker,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        max_observations: int = DEFAULT_MAX_OBSERVATIONS,
    ) -> None:
        if not callable(getattr(retrieval, "retrieve_first_stage", None)):
            raise TypeError("retrieval must implement retrieve_first_stage")
        if not callable(getattr(query_encoder, "encode_query", None)):
            raise TypeError("query_encoder must implement encode_query")
        if not callable(getattr(reranker, "rerank", None)):
            raise TypeError("reranker must implement rerank")
        if isinstance(candidate_limit, bool) or not isinstance(candidate_limit, int):
            raise TypeError("candidate_limit must be an integer")
        if candidate_limit <= 0:
            raise ValueError("candidate_limit must be positive")
        if isinstance(max_observations, bool) or not isinstance(max_observations, int):
            raise TypeError("max_observations must be an integer")
        if max_observations <= 0:
            raise ValueError("max_observations must be positive")

        self._retrieval = retrieval
        self._query_encoder = query_encoder
        self._reranker = reranker
        self._candidate_limit = candidate_limit
        self._observations: deque[MemoryContextShadowObservation] = deque(
            maxlen=max_observations
        )
        self._tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pending_task_count(self) -> int:
        return len(self._tasks)

    @property
    def observations(self) -> tuple[MemoryContextShadowObservation, ...]:
        return tuple(self._observations)

    def observe_turn(self, turn: ConversationTurn) -> None:
        """Schedule shadow retrieval without delaying the conversation callback."""

        if self._closed or turn.role is not ConversationRole.USER:
            return
        task = asyncio.create_task(
            self._process_turn(turn),
            name=f"jarvis-memory-context-shadow-{turn.turn_id[:8]}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    async def wait_idle(self) -> None:
        """Wait for currently scheduled shadow work; intended for validation only."""

        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def _process_turn(self, turn: ConversationTurn) -> None:
        started = time.perf_counter()
        try:
            query_vector = await asyncio.to_thread(
                self._query_encoder.encode_query,
                turn.text,
            )
            candidates = await self._retrieval.retrieve_first_stage(
                turn.text,
                query_vector,
                eligibility=RetrievalEligibility.cloud_context(),
                limit=self._candidate_limit,
            )
            reranked = await asyncio.to_thread(
                self._reranker.rerank,
                turn.text,
                candidates,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception(
                "Phase-4.5E memory context shadow failed for turn %s; "
                "conversation and provider context are unaffected",
                turn.turn_id,
            )
            return

        if self._closed:
            return
        latency_ms = (time.perf_counter() - started) * 1000.0
        observation = MemoryContextShadowObservation(
            turn_id=turn.turn_id,
            reranked_candidates=tuple(reranked),
            latency_ms=latency_ms,
        )
        self._observations.append(observation)
        LOGGER.info(
            "Phase-4.5E memory context shadow turn %s | candidates=%s | "
            "assertion_ids=%s | latency_ms=%.3f | context_injection=False",
            turn.turn_id,
            len(observation.reranked_candidates),
            observation.assertion_ids,
            observation.latency_ms,
        )

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        task.result()

    def close(self) -> None:
        """Cancel session work and dispose all session-local shadow evidence."""

        if self._closed:
            return
        self._closed = True
        cancelled_tasks = len(self._tasks)
        disposed_observations = len(self._observations)
        for task in tuple(self._tasks):
            task.cancel()
        self._observations.clear()
        LOGGER.info(
            "Phase-4.5E memory context shadow closed | cancelled_tasks=%s | "
            "disposed_observations=%s | context_injection=False",
            cancelled_tasks,
            disposed_observations,
        )
