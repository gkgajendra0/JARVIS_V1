from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from .assertions import SemanticAssertionRecord
from .embeddings import (
    QWEN3_EMBEDDING_CONTRACT,
    EmbeddingContract,
    deserialize_embedding,
    embedding_content_sha256,
)
from .storage_rows import (
    SEMANTIC_ASSERTION_COLUMNS_SQL,
    semantic_assertion_record_from_row,
)
from .types import AuthorityClass, Sensitivity
from .worker import SerialConnectionWorker

RRF_K = 60
FTS_WINDOW = 10

_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "what",
        "which",
        "who",
        "why",
        "how",
        "does",
        "do",
        "did",
        "my",
        "me",
        "i",
        "our",
        "to",
        "for",
        "of",
        "in",
        "on",
        "it",
        "this",
        "that",
        "can",
        "ka",
        "ki",
        "kya",
        "hai",
        "hoon",
        "main",
        "mera",
        "meri",
        "kaunsa",
        "kaunsi",
        "abhi",
    }
)

_DEFAULT_AUTHORITIES = frozenset(
    {
        AuthorityClass.OWNER_EXPLICIT,
        AuthorityClass.OWNER_DIRECT,
        AuthorityClass.AUTHORITATIVE_RUNTIME,
        AuthorityClass.VERIFIED,
        AuthorityClass.INFERRED,
    }
)
_LOCAL_SENSITIVITIES = frozenset(
    {
        Sensitivity.STANDARD,
        Sensitivity.PRIVATE,
        Sensitivity.LOCAL_ONLY,
    }
)
_CLOUD_SAFE_SENSITIVITIES = frozenset(
    {
        Sensitivity.STANDARD,
        Sensitivity.PRIVATE,
    }
)


class MemoryRetrievalError(RuntimeError):
    pass


class MemoryRetrievalQueryError(MemoryRetrievalError):
    pass


@dataclass(frozen=True, slots=True)
class RetrievalEligibility:
    authorities: frozenset[AuthorityClass]
    sensitivities: frozenset[Sensitivity]

    def __post_init__(self) -> None:
        if not isinstance(self.authorities, frozenset) or not all(
            isinstance(value, AuthorityClass) for value in self.authorities
        ):
            raise TypeError("authorities must be a frozenset[AuthorityClass]")
        if not isinstance(self.sensitivities, frozenset) or not all(
            isinstance(value, Sensitivity) for value in self.sensitivities
        ):
            raise TypeError("sensitivities must be a frozenset[Sensitivity]")
        if AuthorityClass.UNTRUSTED in self.authorities:
            raise ValueError("untrusted memory authority cannot enter retrieval")
        if Sensitivity.SECRET_PROHIBITED in self.sensitivities:
            raise ValueError("secret-prohibited memory cannot enter retrieval")

    @classmethod
    def local(cls) -> RetrievalEligibility:
        return cls(
            authorities=_DEFAULT_AUTHORITIES,
            sensitivities=_LOCAL_SENSITIVITIES,
        )

    @classmethod
    def cloud_context(cls) -> RetrievalEligibility:
        return cls(
            authorities=_DEFAULT_AUTHORITIES,
            sensitivities=_CLOUD_SAFE_SENSITIVITIES,
        )


@dataclass(frozen=True, slots=True)
class FusedRank:
    assertion_id: str
    fused_score: float
    lexical_rank: int | None
    dense_rank: int | None


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    assertion: SemanticAssertionRecord
    fused_rank: int
    fused_score: float
    lexical_rank: int | None
    lexical_score: float | None
    dense_rank: int | None
    dense_score: float | None


def build_fts5_query(text: str) -> str:
    """Convert natural text to the exact safe lexical grammar used in research."""

    if not isinstance(text, str):
        raise TypeError("FTS query text must be a string")
    tokens = [
        token.casefold()
        for token in re.findall(r"[^\W_]+", text, flags=re.UNICODE)
        if len(token) >= 2 and token.casefold() not in _STOPWORDS
    ]
    tokens = list(dict.fromkeys(tokens))
    if not tokens:
        return '"__no_match__"'
    escaped = [f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens]
    return " OR ".join(escaped)


def reciprocal_rank_fuse(
    lexical_ids: list[str],
    dense_ids: list[str],
    *,
    rank_constant: int = RRF_K,
) -> tuple[FusedRank, ...]:
    if isinstance(rank_constant, bool) or not isinstance(rank_constant, int):
        raise TypeError("rank_constant must be an integer")
    if rank_constant <= 0:
        raise ValueError("rank_constant must be positive")
    if len(lexical_ids) != len(set(lexical_ids)):
        raise ValueError("lexical_ids must not contain duplicates")
    if len(dense_ids) != len(set(dense_ids)):
        raise ValueError("dense_ids must not contain duplicates")

    lexical_rank = {
        assertion_id: rank for rank, assertion_id in enumerate(lexical_ids, start=1)
    }
    dense_rank = {
        assertion_id: rank for rank, assertion_id in enumerate(dense_ids, start=1)
    }
    candidates = set(lexical_rank) | set(dense_rank)
    scores: dict[str, float] = {}
    for assertion_id in candidates:
        score = 0.0
        if assertion_id in lexical_rank:
            score += 1.0 / (rank_constant + lexical_rank[assertion_id])
        if assertion_id in dense_rank:
            score += 1.0 / (rank_constant + dense_rank[assertion_id])
        scores[assertion_id] = score

    ranked = sorted(
        candidates,
        key=lambda assertion_id: (
            -scores[assertion_id],
            dense_rank.get(assertion_id, 10**9),
            lexical_rank.get(assertion_id, 10**9),
            assertion_id,
        ),
    )
    return tuple(
        FusedRank(
            assertion_id=assertion_id,
            fused_score=scores[assertion_id],
            lexical_rank=lexical_rank.get(assertion_id),
            dense_rank=dense_rank.get(assertion_id),
        )
        for assertion_id in ranked
    )


def _query_vector(
    vector: np.ndarray | list[float] | tuple[float, ...],
    contract: EmbeddingContract,
) -> np.ndarray:
    try:
        array = np.asarray(vector, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise MemoryRetrievalQueryError("query vector must be numeric") from exc
    if array.ndim != 1 or array.shape[0] != contract.dimension:
        raise MemoryRetrievalQueryError(
            f"query vector must have shape ({contract.dimension},)"
        )
    if not np.all(np.isfinite(array)):
        raise MemoryRetrievalQueryError("query vector must contain only finite values")
    norm = float(np.linalg.norm(array))
    if not np.isfinite(norm) or norm <= 0.0:
        raise MemoryRetrievalQueryError("query vector norm must be positive and finite")
    return np.asarray(array / norm, dtype=np.float32)


def _enum_values(values: frozenset[Any]) -> tuple[str, ...]:
    return tuple(sorted(str(value.value) for value in values))


def _in_clause(values: tuple[str, ...]) -> str:
    if not values:
        return "NULL"
    return ", ".join("?" for _ in values)


class SemanticRetrievalService:
    """First-stage eligible-current lexical+dense retrieval with deterministic RRF."""

    def __init__(
        self,
        worker: SerialConnectionWorker,
        *,
        contract: EmbeddingContract = QWEN3_EMBEDDING_CONTRACT,
        fts_window: int = FTS_WINDOW,
        rank_constant: int = RRF_K,
    ) -> None:
        if isinstance(fts_window, bool) or not isinstance(fts_window, int):
            raise TypeError("fts_window must be an integer")
        if fts_window <= 0:
            raise ValueError("fts_window must be positive")
        if isinstance(rank_constant, bool) or not isinstance(rank_constant, int):
            raise TypeError("rank_constant must be an integer")
        if rank_constant <= 0:
            raise ValueError("rank_constant must be positive")
        self._worker = worker
        self._contract = contract
        self._fts_window = fts_window
        self._rank_constant = rank_constant

    async def retrieve_first_stage(
        self,
        query_text: str,
        query_vector: np.ndarray | list[float] | tuple[float, ...],
        *,
        eligibility: RetrievalEligibility | None = None,
        limit: int = 3,
    ) -> tuple[RetrievalCandidate, ...]:
        if not isinstance(query_text, str):
            raise TypeError("query_text must be a string")
        if not query_text.strip():
            raise MemoryRetrievalQueryError("query_text must not be empty")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")
        if limit <= 0:
            raise ValueError("limit must be positive")
        policy = eligibility or RetrievalEligibility.local()
        if not isinstance(policy, RetrievalEligibility):
            raise TypeError("eligibility must be RetrievalEligibility")
        vector = _query_vector(query_vector, self._contract)
        fts_query = build_fts5_query(query_text)
        return await self._worker.run(
            lambda connection: self._retrieve_sync(
                connection,
                fts_query=fts_query,
                query_vector=vector,
                eligibility=policy,
                limit=limit,
            )
        )

    def _retrieve_sync(
        self,
        connection: Any,
        *,
        fts_query: str,
        query_vector: np.ndarray,
        eligibility: RetrievalEligibility,
        limit: int,
    ) -> tuple[RetrievalCandidate, ...]:
        lexical = self._lexical_rank_sync(connection, fts_query, eligibility)
        dense = self._dense_rank_sync(connection, query_vector, eligibility)
        lexical_ids = [assertion_id for assertion_id, _ in lexical]
        dense_ids = [assertion_id for assertion_id, _ in dense]
        fused = reciprocal_rank_fuse(
            lexical_ids,
            dense_ids,
            rank_constant=self._rank_constant,
        )
        selected = fused[:limit]
        if not selected:
            return ()

        records = self._records_sync(
            connection,
            [item.assertion_id for item in selected],
            eligibility,
        )
        lexical_scores = dict(lexical)
        dense_scores = dict(dense)
        output: list[RetrievalCandidate] = []
        for fused_rank, item in enumerate(selected, start=1):
            record = records.get(item.assertion_id)
            if record is None:
                continue
            output.append(
                RetrievalCandidate(
                    assertion=record,
                    fused_rank=fused_rank,
                    fused_score=item.fused_score,
                    lexical_rank=item.lexical_rank,
                    lexical_score=lexical_scores.get(item.assertion_id),
                    dense_rank=item.dense_rank,
                    dense_score=dense_scores.get(item.assertion_id),
                )
            )
        return tuple(output)

    def _lexical_rank_sync(
        self,
        connection: Any,
        fts_query: str,
        eligibility: RetrievalEligibility,
    ) -> list[tuple[str, float]]:
        authorities = _enum_values(eligibility.authorities)
        sensitivities = _enum_values(eligibility.sensitivities)
        if not authorities or not sensitivities:
            return []
        rows = connection.execute(
            f"""
            SELECT
                current.assertion_id,
                bm25(semantic_assertion_fts) AS lexical_score
            FROM semantic_assertion_fts
            JOIN current_semantic_assertion AS current
              ON current.assertion_rowid = semantic_assertion_fts.rowid
            WHERE semantic_assertion_fts MATCH ?
              AND current.sensitivity IN ({_in_clause(sensitivities)})
              AND current.source_id IN (
                  SELECT source_id
                  FROM memory_source
                  WHERE authority_class IN ({_in_clause(authorities)})
                    AND sensitivity IN ({_in_clause(sensitivities)})
              )
            ORDER BY lexical_score ASC, current.assertion_id ASC
            LIMIT ?
            """,
            (
                fts_query,
                *sensitivities,
                *authorities,
                *sensitivities,
                self._fts_window,
            ),
        ).fetchall()
        return [(str(row[0]), float(row[1])) for row in rows]

    def _dense_rank_sync(
        self,
        connection: Any,
        query_vector: np.ndarray,
        eligibility: RetrievalEligibility,
    ) -> list[tuple[str, float]]:
        authorities = _enum_values(eligibility.authorities)
        sensitivities = _enum_values(eligibility.sensitivities)
        if not authorities or not sensitivities:
            return []
        contract = self._contract
        rows = connection.execute(
            f"""
            SELECT
                current_rows.*,
                embedding.content_sha256,
                embedding.embedding_blob
            FROM (
                SELECT {SEMANTIC_ASSERTION_COLUMNS_SQL}
                FROM current_semantic_assertion
                WHERE sensitivity IN ({_in_clause(sensitivities)})
                  AND source_id IN (
                      SELECT source_id
                      FROM memory_source
                      WHERE authority_class IN ({_in_clause(authorities)})
                        AND sensitivity IN ({_in_clause(sensitivities)})
                  )
            ) AS current_rows
            JOIN semantic_assertion_embedding AS embedding
              ON embedding.assertion_id = current_rows.assertion_id
            WHERE embedding.model_id = ?
              AND embedding.model_revision = ?
              AND embedding.dimension = ?
              AND embedding.dtype = ?
              AND embedding.byte_order = ?
              AND embedding.normalized = ?
            ORDER BY current_rows.assertion_id ASC
            """,
            (
                *sensitivities,
                *authorities,
                *sensitivities,
                contract.model_id,
                contract.model_revision,
                contract.dimension,
                contract.dtype,
                contract.byte_order,
                int(contract.normalized),
            ),
        ).fetchall()

        ranked: list[tuple[str, float]] = []
        for row in rows:
            record = semantic_assertion_record_from_row(row[:21])
            stored_fingerprint = str(row[21]).casefold()
            if stored_fingerprint != embedding_content_sha256(record.normalized_text):
                continue
            document_vector = deserialize_embedding(row[22], contract=contract)
            score = float(
                np.dot(
                    document_vector.astype(np.float64, copy=False),
                    query_vector.astype(np.float64, copy=False),
                )
            )
            if not np.isfinite(score):
                continue
            ranked.append((record.assertion_id, score))
        ranked.sort(key=lambda item: (-item[1], item[0]))
        return ranked

    def _records_sync(
        self,
        connection: Any,
        assertion_ids: list[str],
        eligibility: RetrievalEligibility,
    ) -> dict[str, SemanticAssertionRecord]:
        if not assertion_ids:
            return {}
        authorities = _enum_values(eligibility.authorities)
        sensitivities = _enum_values(eligibility.sensitivities)
        if not authorities or not sensitivities:
            return {}
        rows = connection.execute(
            f"""
            SELECT {SEMANTIC_ASSERTION_COLUMNS_SQL}
            FROM current_semantic_assertion
            WHERE assertion_id IN ({_in_clause(tuple(assertion_ids))})
              AND sensitivity IN ({_in_clause(sensitivities)})
              AND source_id IN (
                  SELECT source_id
                  FROM memory_source
                  WHERE authority_class IN ({_in_clause(authorities)})
                    AND sensitivity IN ({_in_clause(sensitivities)})
              )
            """,
            (
                *assertion_ids,
                *sensitivities,
                *authorities,
                *sensitivities,
            ),
        ).fetchall()
        records = [semantic_assertion_record_from_row(row) for row in rows]
        return {record.assertion_id: record for record in records}
