"""PI-1B source-backed read-only SHADOW tests: no real owner data/cloud calls."""

from __future__ import annotations

import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.personal_context_shadow import (
    ShadowDisposition,
    ShadowPersonalContextCoordinator,
)
from jarvis.memory.provenance import MemorySource
from jarvis.memory.query import CanonicalMemoryReader
from jarvis.memory.query_plan import MemoryFacetKey
from jarvis.memory.retrieval import SemanticRetrievalService
from jarvis.memory.service import MemoryService
from jarvis.memory.types import AuthorityClass, MemorySourceClass, Sensitivity
from jarvis.memory.worker import SerialConnectionWorker

BASE = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)


def _ids(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter)}"


def _source(source_id: str, sensitivity: Sensitivity) -> MemorySource:
    return MemorySource(
        source_id=source_id,
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        canonical_ref=f"synthetic:turn:{source_id}",
        observed_at=BASE,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
        sensitivity=sensitivity,
        created_at=BASE,
    )


class FixtureSelector:
    def __init__(self, predicate: str) -> None:
        self._predicate = predicate
        self.called = False

    async def select(self, question, catalog):
        del question
        self.called = True
        return tuple(
            facet for facet in catalog.facets if facet.predicate == self._predicate
        )


class FabricatingSelector:
    async def select(self, question, catalog):
        del question, catalog
        return (MemoryFacetKey("personal", "owner", "fabricated"),)


@pytest.mark.asyncio
async def test_shadow_current_fact_correction_budget_guest_and_safe_release(
    tmp_path: Path,
) -> None:
    path = tmp_path / "synthetic.db"

    def factory():
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    writer = SerialConnectionWorker(factory, thread_name="pi1b-writer")
    reader = SerialConnectionWorker(factory, thread_name="pi1b-reader")
    lifecycle = MemoryLifecycleService(
        writer,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    service = MemoryService(lifecycle, CanonicalMemoryReader(reader))
    retrieval = SemanticRetrievalService(reader)
    selector = FixtureSelector("diet_preference")
    coordinator = ShadowPersonalContextCoordinator(
        retrieval=retrieval, selector=selector, byte_budget=100, max_facts=2
    )
    try:
        old = await service.remember_text(
            predicate="diet preference",
            value="eat meat",
            source=_source("old", Sensitivity.STANDARD),
        )
        updated = await service.correct_text(
            predicate="diet preference",
            value="vegetarian meals",
            source=_source("correct", Sensitivity.STANDARD),
        )
        await service.remember_text(
            predicate="secret hobby",
            value="LOCAL-CANARY-NEVER-EXPORT",
            source=_source("secret", Sensitivity.LOCAL_ONLY),
            sensitivity=Sensitivity.LOCAL_ONLY,
        )
        await service.remember_text(
            predicate="private plan",
            value="private itinerary",
            source=_source("private", Sensitivity.PRIVATE),
            sensitivity=Sensitivity.PRIVATE,
        )
        result = await coordinator.select_context(
            "What could I eat?", authenticated_owner=True
        )
        assert result.mode == "shadow"
        assert result.disposition is ShadowDisposition.SELECTED
        assert len(result.facts) == 1
        assert result.facts[0].assertion_id == updated.record.assertion_id
        assert result.facts[0].assertion_id != old.record.assertion_id
        assert "vegetarian meals" in result.facts[0].compact_text
        assert "LOCAL-CANARY" not in str(result)
        with pytest.raises(RuntimeError, match="cannot be sent"):
            result.export_to_provider()
        selector.called = False
        guest = await coordinator.select_context(
            "What should the owner eat?", authenticated_owner=False
        )
        assert guest.disposition is ShadowDisposition.DENIED
        assert guest.facts == ()
        assert selector.called is False

        # The low budget keeps eligible bytes out of the packet.
        low = ShadowPersonalContextCoordinator(
            retrieval=retrieval, selector=selector, byte_budget=2
        )
        dropped = await low.select_context(
            "What could I eat?", authenticated_owner=True
        )
        assert dropped.disposition is ShadowDisposition.NO_MATCH
        assert dropped.dropped_count == 1

        await service.forget_exact(
            predicate="diet preference",
            source=_source("forget", Sensitivity.STANDARD),
        )
        forgotten = await coordinator.select_context(
            "What could I eat?", authenticated_owner=True
        )
        assert forgotten.disposition is ShadowDisposition.NO_MATCH
        assert forgotten.facts == ()
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_shadow_unknown_facet_proposal_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "empty.db"

    def factory():
        connection = sqlite3.connect(path)
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    reader = SerialConnectionWorker(factory, thread_name="pi1b-empty")
    coordinator = ShadowPersonalContextCoordinator(
        retrieval=SemanticRetrievalService(reader), selector=FabricatingSelector()
    )
    try:
        result = await coordinator.select_context(
            "Anything about my history?", authenticated_owner=True
        )
        assert result.disposition is ShadowDisposition.UNAVAILABLE
        assert result.facts == ()
    finally:
        await reader.close()


def test_shadow_coordinator_rejects_wrong_types() -> None:
    with pytest.raises(TypeError, match="canonical"):
        ShadowPersonalContextCoordinator(
            retrieval=object(),
            selector=FixtureSelector("x"),  # type: ignore[arg-type]
        )
