from __future__ import annotations

import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.memory.assertions import SemanticAssertionDraft
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.provenance import MemorySource
from jarvis.memory.query_plan import MemoryFacetKey
from jarvis.memory.retrieval import RetrievalEligibility, SemanticRetrievalService
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker

BASE = datetime(2026, 9, 6, 12, 30, tzinfo=UTC)


def _worker(path: Path) -> SerialConnectionWorker:
    def factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    return SerialConnectionWorker(factory, thread_name="exact-facet-lookup-test")


def _ids(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter)}"


def _source(
    source_id: str,
    *,
    authority: AuthorityClass = AuthorityClass.OWNER_EXPLICIT,
    sensitivity: Sensitivity = Sensitivity.STANDARD,
) -> MemorySource:
    return MemorySource(
        source_id=source_id,
        source_class=(
            MemorySourceClass.EXTERNAL_WEB
            if authority is AuthorityClass.UNTRUSTED
            else MemorySourceClass.OWNER_EXPLICIT
        ),
        canonical_ref=f"exact-facet:{source_id}",
        observed_at=BASE,
        authority_class=authority,
        sensitivity=sensitivity,
        created_at=BASE,
    )


def _draft(
    value: str,
    *,
    sensitivity: Sensitivity = Sensitivity.STANDARD,
) -> SemanticAssertionDraft:
    return SemanticAssertionDraft(
        subject_scope="profile",
        subject="Aquila",
        predicate="archive_destination",
        value_type=ValueType.TEXT,
        value=value,
        normalized_text=f"Aquila archive destination is {value}.",
        freshness_class=FreshnessClass.STABLE,
        sensitivity=sensitivity,
    )


@pytest.mark.asyncio
async def test_exact_lookup_needs_no_embedding_or_semantic_ranking(tmp_path: Path) -> None:
    worker = _worker(tmp_path / "exact.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    retrieval = SemanticRetrievalService(worker)
    try:
        assertion = await lifecycle.create(
            _draft("vault-A"),
            _source("owner-source"),
        )

        records = await retrieval.retrieve_exact_current_facet(
            MemoryFacetKey("profile", "Aquila", "archive_destination"),
            eligibility=RetrievalEligibility.cloud_context(),
        )

        assert [record.assertion_id for record in records] == [assertion.assertion_id]
        assert records[0].value == "vault-A"
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_exact_lookup_returns_all_conflicting_current_rows_for_fail_closed_gate(
    tmp_path: Path,
) -> None:
    worker = _worker(tmp_path / "conflict.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    retrieval = SemanticRetrievalService(worker)
    try:
        first = await lifecycle.create(_draft("vault-A"), _source("first-source"))
        second = await lifecycle.create(_draft("vault-B"), _source("second-source"))

        records = await retrieval.retrieve_exact_current_facet(
            MemoryFacetKey("profile", "Aquila", "archive_destination")
        )

        assert {record.assertion_id for record in records} == {
            first.assertion_id,
            second.assertion_id,
        }
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_exact_cloud_lookup_preserves_security_and_current_state(tmp_path: Path) -> None:
    worker = _worker(tmp_path / "security.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    retrieval = SemanticRetrievalService(worker)
    try:
        local_only = await lifecycle.create(
            _draft("local-vault", sensitivity=Sensitivity.LOCAL_ONLY),
            _source("local-source", sensitivity=Sensitivity.LOCAL_ONLY),
        )
        untrusted = await lifecycle.create(
            _draft("rumor-vault"),
            _source("rumor-source", authority=AuthorityClass.UNTRUSTED),
        )

        cloud_records = await retrieval.retrieve_exact_current_facet(
            MemoryFacetKey("profile", "Aquila", "archive_destination"),
            eligibility=RetrievalEligibility.cloud_context(),
        )

        assert local_only.assertion_id not in {
            record.assertion_id for record in cloud_records
        }
        assert untrusted.assertion_id not in {
            record.assertion_id for record in cloud_records
        }
    finally:
        await worker.close()
