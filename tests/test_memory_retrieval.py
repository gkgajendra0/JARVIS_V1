from __future__ import annotations

import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from jarvis.memory.assertions import SemanticAssertionDraft
from jarvis.memory.embeddings import SemanticEmbeddingStore
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.provenance import MemorySource
from jarvis.memory.retrieval import (
    RetrievalEligibility,
    SemanticRetrievalService,
    build_fts5_query,
    reciprocal_rank_fuse,
)
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker

BASE = datetime(2026, 9, 5, 18, 30, tzinfo=UTC)


def worker_for(path: Path) -> SerialConnectionWorker:
    def connection_factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    return SerialConnectionWorker(
        connection_factory,
        thread_name="jarvis-memory-retrieval-test",
    )


def id_factory(prefix: str):
    values = itertools.count(1)
    return lambda: f"{prefix}-{next(values)}"


def source(
    source_id: str,
    *,
    authority: AuthorityClass = AuthorityClass.OWNER_EXPLICIT,
    sensitivity: Sensitivity = Sensitivity.STANDARD,
) -> MemorySource:
    source_class = (
        MemorySourceClass.EXTERNAL_WEB
        if authority is AuthorityClass.UNTRUSTED
        else MemorySourceClass.OWNER_EXPLICIT
    )
    return MemorySource(
        source_id=source_id,
        source_class=source_class,
        canonical_ref=f"retrieval-test:{source_id}",
        observed_at=BASE,
        authority_class=authority,
        sensitivity=sensitivity,
        created_at=BASE,
    )


def draft(
    predicate: str,
    text: str,
    *,
    sensitivity: Sensitivity = Sensitivity.STANDARD,
) -> SemanticAssertionDraft:
    return SemanticAssertionDraft(
        subject_scope="owner",
        subject="owner",
        predicate=predicate,
        value_type=ValueType.TEXT,
        value=text,
        normalized_text=text,
        freshness_class=FreshnessClass.STABLE,
        sensitivity=sensitivity,
    )


def basis(index: int) -> np.ndarray:
    vector = np.zeros(256, dtype=np.float32)
    vector[index] = 1.0
    return vector


def test_fts_query_quotes_natural_tokens_and_never_exposes_operators() -> None:
    query = build_fts5_query('OR bike: "Jimny"?? bank* bike')

    assert query == '"or" OR "bike" OR "jimny" OR "bank"'
    assert ":" not in query
    assert "*" not in query
    assert build_fts5_query("? ! _") == '"__no_match__"'


def test_rrf_exact_score_tie_prefers_dense_then_lexical_then_id() -> None:
    fused = reciprocal_rank_fuse(["a", "b"], ["b", "a"])

    assert fused[0].assertion_id == "b"
    assert fused[0].fused_score == fused[1].fused_score
    assert fused[0].dense_rank == 1
    assert fused[1].dense_rank == 2

    id_tie = reciprocal_rank_fuse(["a", "b"], [])
    assert [item.assertion_id for item in id_tie] == ["a", "b"]


def test_retrieval_eligibility_fails_closed_for_untrusted_or_secret() -> None:
    with pytest.raises(ValueError, match="untrusted"):
        RetrievalEligibility(
            authorities=frozenset({AuthorityClass.UNTRUSTED}),
            sensitivities=frozenset({Sensitivity.STANDARD}),
        )

    with pytest.raises(ValueError, match="secret-prohibited"):
        RetrievalEligibility(
            authorities=frozenset({AuthorityClass.OWNER_EXPLICIT}),
            sensitivities=frozenset({Sensitivity.SECRET_PROHIBITED}),
        )


@pytest.mark.asyncio
async def test_retrieval_filters_current_authority_and_sensitivity_before_ranking(
    tmp_path: Path,
) -> None:
    worker = worker_for(tmp_path / "eligible.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=id_factory("assertion"),
        operation_id_factory=id_factory("operation"),
    )
    embeddings = SemanticEmbeddingStore(worker, clock=lambda: BASE)
    retrieval = SemanticRetrievalService(worker)
    try:
        standard = await lifecycle.create(
            draft("camera_standard", "camera pocket sensor"),
            source("standard-source"),
        )
        await embeddings.upsert(
            standard.assertion_id,
            normalized_text=standard.normalized_text,
            vector=basis(0),
        )

        local_only = await lifecycle.create(
            draft(
                "camera_local",
                "camera local private sensor",
                sensitivity=Sensitivity.LOCAL_ONLY,
            ),
            source("local-source", sensitivity=Sensitivity.LOCAL_ONLY),
        )
        await embeddings.upsert(
            local_only.assertion_id,
            normalized_text=local_only.normalized_text,
            vector=basis(0),
        )

        untrusted = await lifecycle.create(
            draft("camera_untrusted", "camera hostile external sensor"),
            source("untrusted-source", authority=AuthorityClass.UNTRUSTED),
        )
        await embeddings.upsert(
            untrusted.assertion_id,
            normalized_text=untrusted.normalized_text,
            vector=basis(0),
        )

        historical = await lifecycle.create(
            draft("camera_history", "camera historical old sensor"),
            source("history-source"),
        )
        await embeddings.upsert(
            historical.assertion_id,
            normalized_text=historical.normalized_text,
            vector=basis(0),
        )
        replacement = await lifecycle.historical_change(
            historical.assertion_id,
            draft("camera_history", "replacement current sensor"),
            source("history-change-source"),
            effective_at=BASE,
        )

        cloud = await retrieval.retrieve_first_stage(
            "camera sensor",
            basis(0),
            eligibility=RetrievalEligibility.cloud_context(),
            limit=10,
        )
        cloud_ids = {candidate.assertion.assertion_id for candidate in cloud}
        assert standard.assertion_id in cloud_ids
        assert local_only.assertion_id not in cloud_ids
        assert untrusted.assertion_id not in cloud_ids
        assert historical.assertion_id not in cloud_ids
        assert replacement.assertion_id in cloud_ids
        replacement_candidate = next(
            candidate
            for candidate in cloud
            if candidate.assertion.assertion_id == replacement.assertion_id
        )
        assert replacement_candidate.lexical_rank is not None
        assert replacement_candidate.dense_rank is None

        local = await retrieval.retrieve_first_stage(
            "camera sensor",
            basis(0),
            eligibility=RetrievalEligibility.local(),
            limit=10,
        )
        local_ids = {candidate.assertion.assertion_id for candidate in local}
        assert standard.assertion_id in local_ids
        assert local_only.assertion_id in local_ids
        assert untrusted.assertion_id not in local_ids
        assert historical.assertion_id not in local_ids
        assert replacement.assertion_id in local_ids
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_stale_content_fingerprint_cannot_enter_dense_retrieval(
    tmp_path: Path,
) -> None:
    worker = worker_for(tmp_path / "stale.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=id_factory("assertion"),
        operation_id_factory=id_factory("operation"),
    )
    embeddings = SemanticEmbeddingStore(worker, clock=lambda: BASE)
    retrieval = SemanticRetrievalService(worker)
    try:
        assertion = await lifecycle.create(
            draft("stale", "stale semantic original"),
            source("stale-source"),
        )
        await embeddings.upsert(
            assertion.assertion_id,
            normalized_text=assertion.normalized_text,
            vector=basis(0),
        )
        await worker.run(
            lambda connection: connection.execute(
                "UPDATE semantic_assertion SET normalized_text = ? WHERE assertion_id = ?",
                ("changed canonical representation", assertion.assertion_id),
            )
        )

        results = await retrieval.retrieve_first_stage(
            "zzzznomatch",
            basis(0),
            limit=10,
        )

        assert results == ()
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_dense_ranking_and_candidate_metadata_are_deterministic(
    tmp_path: Path,
) -> None:
    worker = worker_for(tmp_path / "dense.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=id_factory("assertion"),
        operation_id_factory=id_factory("operation"),
    )
    embeddings = SemanticEmbeddingStore(worker, clock=lambda: BASE)
    retrieval = SemanticRetrievalService(worker)
    try:
        best = await lifecycle.create(
            draft("dense_best", "alpha memory"),
            source("best-source"),
        )
        second = await lifecycle.create(
            draft("dense_second", "beta memory"),
            source("second-source"),
        )
        await embeddings.upsert(
            best.assertion_id,
            normalized_text=best.normalized_text,
            vector=basis(0),
        )
        mixed = basis(0) + basis(1)
        mixed /= np.linalg.norm(mixed)
        await embeddings.upsert(
            second.assertion_id,
            normalized_text=second.normalized_text,
            vector=mixed,
        )

        results = await retrieval.retrieve_first_stage(
            "zzzznomatch",
            basis(0),
            limit=2,
        )

        assert [item.assertion.assertion_id for item in results] == [
            best.assertion_id,
            second.assertion_id,
        ]
        assert [item.dense_rank for item in results] == [1, 2]
        assert all(item.lexical_rank is None for item in results)
        assert results[0].dense_score == pytest.approx(1.0)
        assert results[0].fused_rank == 1
    finally:
        await worker.close()
