from __future__ import annotations

import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.memory.assertions import SemanticAssertionDraft
from jarvis.memory.evidence_gate import MemoryEvidenceDisposition, MemoryEvidenceGate
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.provenance import MemorySource
from jarvis.memory.query_plan import (
    MemoryQueryIntent,
    MemoryQueryProposal,
    MemoryTemporalScope,
)
from jarvis.memory.retrieval import RetrievalEligibility, SemanticRetrievalService
from jarvis.memory.types import (
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker

BASE = datetime(2026, 9, 6, 13, 0, tzinfo=UTC)


def _worker(path: Path) -> SerialConnectionWorker:
    def factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    return SerialConnectionWorker(factory, thread_name="memory-evidence-gate-test")


def _ids(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter)}"


def _source(
    source_id: str,
    *,
    sensitivity: Sensitivity = Sensitivity.STANDARD,
) -> MemorySource:
    return MemorySource(
        source_id=source_id,
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        canonical_ref=f"evidence-gate:{source_id}",
        observed_at=BASE,
        authority_class="owner_explicit",
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


def _exact_proposal() -> MemoryQueryProposal:
    return MemoryQueryProposal(
        intent=MemoryQueryIntent.EXACT_FACT,
        subject_scope="profile",
        subject="Aquila",
        predicate="archive_destination",
        temporal_scope=MemoryTemporalScope.CURRENT,
        requested_relation="archive destination",
    )


@pytest.mark.asyncio
async def test_unique_exact_current_fact_releases_without_any_cloud_or_embedding(
    tmp_path: Path,
) -> None:
    worker = _worker(tmp_path / "release.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    gate = MemoryEvidenceGate(SemanticRetrievalService(worker))
    try:
        assertion = await lifecycle.create(_draft("vault-A"), _source("owner-source"))

        decision = await gate.evaluate(
            _exact_proposal(),
            eligibility=RetrievalEligibility.cloud_context(),
        )

        assert decision.disposition is MemoryEvidenceDisposition.RELEASE
        assert decision.reason_code == "unique_eligible_current_exact_fact"
        assert decision.evidence is not None
        assert decision.evidence.assertion.assertion_id == assertion.assertion_id
        assert decision.evidence.assertion.value == "vault-A"
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_conflicting_current_exact_facts_fail_closed(tmp_path: Path) -> None:
    worker = _worker(tmp_path / "conflict.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    gate = MemoryEvidenceGate(SemanticRetrievalService(worker))
    try:
        await lifecycle.create(_draft("vault-A"), _source("source-a"))
        await lifecycle.create(_draft("vault-B"), _source("source-b"))

        decision = await gate.evaluate(_exact_proposal())

        assert decision.disposition is MemoryEvidenceDisposition.ABSTAIN
        assert decision.reason_code == "conflicting_current_assertions"
        assert decision.evidence is None
    finally:
        await worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "temporal_scope", "reason"),
    (
        (
            MemoryQueryIntent.QUALIFIED_FACT,
            MemoryTemporalScope.CURRENT,
            "qualified_relation_requires_separate_path",
        ),
        (
            MemoryQueryIntent.EXTERNAL_SOURCE_FACT,
            MemoryTemporalScope.CURRENT,
            "external_source_query_not_canonical_memory",
        ),
        (
            MemoryQueryIntent.EXACT_FACT,
            MemoryTemporalScope.HISTORICAL,
            "historical_query_requires_separate_path",
        ),
    ),
)
async def test_non_exact_current_semantics_never_auto_release(
    tmp_path: Path,
    intent: MemoryQueryIntent,
    temporal_scope: MemoryTemporalScope,
    reason: str,
) -> None:
    worker = _worker(tmp_path / f"{intent.value}-{temporal_scope.value}.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    gate = MemoryEvidenceGate(SemanticRetrievalService(worker))
    try:
        await lifecycle.create(_draft("vault-A"), _source("owner-source"))
        proposal = MemoryQueryProposal(
            intent=intent,
            subject_scope="profile",
            subject="Aquila",
            predicate="archive_destination",
            temporal_scope=temporal_scope,
        )

        decision = await gate.evaluate(proposal)

        assert decision.disposition is MemoryEvidenceDisposition.ABSTAIN
        assert decision.reason_code == reason
        assert decision.evidence is None
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_cloud_gate_cannot_release_local_only_facet_even_when_proposed(
    tmp_path: Path,
) -> None:
    worker = _worker(tmp_path / "local-only.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    gate = MemoryEvidenceGate(SemanticRetrievalService(worker))
    try:
        await lifecycle.create(
            _draft("local-vault", sensitivity=Sensitivity.LOCAL_ONLY),
            _source("local-source", sensitivity=Sensitivity.LOCAL_ONLY),
        )

        decision = await gate.evaluate(
            _exact_proposal(),
            eligibility=RetrievalEligibility.cloud_context(),
        )

        assert decision.disposition is MemoryEvidenceDisposition.ABSTAIN
        assert decision.reason_code == "unknown_canonical_facet"
        assert decision.evidence is None
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_provider_cannot_force_release_by_inventing_known_shape_unknown_facet(
    tmp_path: Path,
) -> None:
    worker = _worker(tmp_path / "invented.db")
    gate = MemoryEvidenceGate(SemanticRetrievalService(worker))
    try:
        proposal = MemoryQueryProposal(
            intent=MemoryQueryIntent.EXACT_FACT,
            subject_scope="profile",
            subject="Aquila",
            predicate="invented_relation",
        )

        decision = await gate.evaluate(proposal)

        assert decision.disposition is MemoryEvidenceDisposition.ABSTAIN
        assert decision.reason_code == "unknown_canonical_facet"
    finally:
        await worker.close()
