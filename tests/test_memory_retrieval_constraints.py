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
from jarvis.memory.query_plan import MemoryFacetKey
from jarvis.memory.retrieval import (
    RetrievalConstraints,
    RetrievalEligibility,
    SemanticRetrievalService,
)
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker

BASE = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def _worker(path: Path) -> SerialConnectionWorker:
    def connection_factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    return SerialConnectionWorker(
        connection_factory,
        thread_name="jarvis-memory-retrieval-constraints-test",
    )


def _id_factory(prefix: str):
    values = itertools.count(1)
    return lambda: f"{prefix}-{next(values)}"


def _source(
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
        canonical_ref=f"constraint-test:{source_id}",
        observed_at=BASE,
        authority_class=authority,
        sensitivity=sensitivity,
        created_at=BASE,
    )


def _draft(
    *,
    subject: str,
    predicate: str,
    text: str,
    sensitivity: Sensitivity = Sensitivity.STANDARD,
) -> SemanticAssertionDraft:
    return SemanticAssertionDraft(
        subject_scope="profile",
        subject=subject,
        predicate=predicate,
        value_type=ValueType.TEXT,
        value=text,
        normalized_text=text,
        freshness_class=FreshnessClass.STABLE,
        sensitivity=sensitivity,
    )


def _basis(index: int) -> np.ndarray:
    vector = np.zeros(256, dtype=np.float32)
    vector[index] = 1.0
    return vector


@pytest.mark.asyncio
async def test_exact_predicate_constraint_applies_before_dense_and_lexical_ranking(
    tmp_path: Path,
) -> None:
    worker = _worker(tmp_path / "predicate.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_id_factory("assertion"),
        operation_id_factory=_id_factory("operation"),
    )
    embeddings = SemanticEmbeddingStore(worker, clock=lambda: BASE)
    retrieval = SemanticRetrievalService(worker)
    try:
        correct = await lifecycle.create(
            _draft(
                subject="Aquila",
                predicate="archive_destination",
                text="Aquila archive destination is vault-A.",
            ),
            _source("correct-source"),
        )
        wrong_relation = await lifecycle.create(
            _draft(
                subject="Aquila",
                predicate="signin_method",
                text="Aquila archive destination signin method is auth-A.",
            ),
            _source("wrong-source"),
        )

        correct_vector = _basis(0) + _basis(1)
        correct_vector /= np.linalg.norm(correct_vector)
        await embeddings.upsert(
            correct.assertion_id,
            normalized_text=correct.normalized_text,
            vector=correct_vector,
        )
        await embeddings.upsert(
            wrong_relation.assertion_id,
            normalized_text=wrong_relation.normalized_text,
            vector=_basis(0),
        )

        unconstrained = await retrieval.retrieve_first_stage(
            "Aquila archive destination",
            _basis(0),
            limit=10,
        )
        assert wrong_relation.assertion_id in {
            item.assertion.assertion_id for item in unconstrained
        }

        constrained = await retrieval.retrieve_first_stage(
            "Aquila archive destination",
            _basis(0),
            constraints=RetrievalConstraints.for_facet(
                MemoryFacetKey("profile", "Aquila", "archive_destination")
            ),
            limit=10,
        )

        assert [item.assertion.assertion_id for item in constrained] == [
            correct.assertion_id
        ]
        assert constrained[0].assertion.predicate == "archive_destination"
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_exact_subject_constraint_prevents_cross_subject_candidate_noise(
    tmp_path: Path,
) -> None:
    worker = _worker(tmp_path / "subject.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_id_factory("assertion"),
        operation_id_factory=_id_factory("operation"),
    )
    embeddings = SemanticEmbeddingStore(worker, clock=lambda: BASE)
    retrieval = SemanticRetrievalService(worker)
    try:
        aquila = await lifecycle.create(
            _draft(
                subject="Aquila",
                predicate="archive_destination",
                text="Aquila archive destination is vault-A.",
            ),
            _source("aquila-source"),
        )
        boreal = await lifecycle.create(
            _draft(
                subject="Boreal",
                predicate="archive_destination",
                text="Boreal archive destination is vault-B.",
            ),
            _source("boreal-source"),
        )
        await embeddings.upsert(
            aquila.assertion_id,
            normalized_text=aquila.normalized_text,
            vector=_basis(0),
        )
        await embeddings.upsert(
            boreal.assertion_id,
            normalized_text=boreal.normalized_text,
            vector=_basis(0),
        )

        constrained = await retrieval.retrieve_first_stage(
            "archive destination",
            _basis(0),
            constraints=RetrievalConstraints(
                subject_scope="profile",
                subject="Aquila",
                predicate="archive_destination",
            ),
            limit=10,
        )

        assert [item.assertion.assertion_id for item in constrained] == [
            aquila.assertion_id
        ]
        assert boreal.assertion_id not in {
            item.assertion.assertion_id for item in constrained
        }
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_cloud_facet_catalog_exposes_only_already_eligible_current_facets(
    tmp_path: Path,
) -> None:
    worker = _worker(tmp_path / "catalog.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_id_factory("assertion"),
        operation_id_factory=_id_factory("operation"),
    )
    retrieval = SemanticRetrievalService(worker)
    try:
        visible = await lifecycle.create(
            _draft(
                subject="Aquila",
                predicate="archive_destination",
                text="Aquila archive destination is vault-A.",
            ),
            _source("visible-source"),
        )
        local_only = await lifecycle.create(
            _draft(
                subject="Aquila",
                predicate="local_diagnostic_slot",
                text="Aquila local diagnostic slot is local-A.",
                sensitivity=Sensitivity.LOCAL_ONLY,
            ),
            _source("local-source", sensitivity=Sensitivity.LOCAL_ONLY),
        )
        untrusted = await lifecycle.create(
            _draft(
                subject="Aquila",
                predicate="rumored_destination",
                text="A rumor claims Aquila uses rumor-A.",
            ),
            _source("untrusted-source", authority=AuthorityClass.UNTRUSTED),
        )
        historical = await lifecycle.create(
            _draft(
                subject="Aquila",
                predicate="old_timezone",
                text="Aquila old timezone was tz-old.",
            ),
            _source("history-source"),
        )
        await lifecycle.historical_change(
            historical.assertion_id,
            _draft(
                subject="Aquila",
                predicate="current_timezone",
                text="Aquila current timezone is tz-new.",
            ),
            _source("history-change-source"),
            effective_at=BASE,
        )

        cloud = await retrieval.eligible_facet_catalog(
            eligibility=RetrievalEligibility.cloud_context()
        )

        assert MemoryFacetKey(
            "profile", "Aquila", visible.predicate
        ) in cloud.facets
        assert MemoryFacetKey(
            "profile", "Aquila", local_only.predicate
        ) not in cloud.facets
        assert MemoryFacetKey(
            "profile", "Aquila", untrusted.predicate
        ) not in cloud.facets
        assert MemoryFacetKey("profile", "Aquila", "old_timezone") not in cloud.facets
        assert MemoryFacetKey(
            "profile", "Aquila", "current_timezone"
        ) in cloud.facets
    finally:
        await worker.close()


def test_retrieval_constraints_reject_empty_or_invalid_values() -> None:
    with pytest.raises(ValueError, match="predicate"):
        RetrievalConstraints(predicate="   ")
    with pytest.raises(TypeError, match="subject"):
        RetrievalConstraints(subject=42)  # type: ignore[arg-type]
