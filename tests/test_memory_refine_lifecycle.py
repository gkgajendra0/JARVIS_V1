"""Slice 1 lifecycle semantics: refine (true but less complete), a real-world
change whose effective time is unknown, and the contrast with correct."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_memory_lifecycle import BASE, draft, service_for, source, worker_for

from jarvis.memory.assertions import SemanticAssertionDraft
from jarvis.memory.lifecycle import MemoryLifecycleError
from jarvis.memory.types import AssertionState, FreshnessClass, Sensitivity, ValueType


async def operations(worker, target_id):
    return await worker.run(
        lambda c: c.execute(
            "SELECT operation_type, reason_code FROM memory_operation"
            " WHERE target_id=? ORDER BY occurred_at, operation_id",
            (target_id,),
        ).fetchall()
    )


async def current_ids(worker):
    return await worker.run(
        lambda c: [
            r[0]
            for r in c.execute(
                "SELECT assertion_id FROM current_semantic_assertion"
                " ORDER BY assertion_id"
            )
        ]
    )


@pytest.mark.asyncio
async def test_refine_keeps_earlier_true_fact_unretracted_and_validity_untouched(
    tmp_path: Path,
) -> None:
    """Design §4.6: "I have a Tigor", then "bought it in March 2017". The
    earlier row was true but less complete - never retracted (false), never
    given an end of validity (former possession)."""
    worker = worker_for(tmp_path / "refine.db")
    service = service_for(worker)
    try:
        owned = await service.create(draft("Tigor", "tigor"), source("s-create"))
        refined = await service.refine(
            owned.assertion_id,
            draft("Tigor; acquired March 2017", "tigor 2017-03"),
            source("s-refine"),
        )
        earlier = await service.get(owned.assertion_id)
        assert earlier.state is AssertionState.SUPERSEDED
        assert earlier.state is not AssertionState.RETRACTED
        assert earlier.valid_from is None and earlier.valid_to is None
        assert earlier.system_to == BASE
        assert refined.state is AssertionState.ACTIVE
        assert refined.supersedes_id == owned.assertion_id
        assert refined.predicate == owned.predicate
        assert refined.valid_from is None  # month precision: unknown boundary
        assert await current_ids(worker) == [refined.assertion_id]
        assert await operations(worker, refined.assertion_id) == [("refine", None)]
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_refine_inherits_or_takes_a_stated_day_boundary(tmp_path: Path) -> None:
    worker = worker_for(tmp_path / "refine-day.db")
    service = service_for(worker)
    try:
        known = datetime(2023, 3, 13, 18, 30, tzinfo=UTC)  # 14 Mar local (+05:30)
        first = await service.create(
            draft("ThinkPad", "tp", valid_from=known), source("s1")
        )
        inherited = await service.refine(
            first.assertion_id, draft("ThinkPad X1", "tp x1"), source("s2")
        )
        assert inherited.valid_from == known
        none_yet = await service.create(
            SemanticAssertionDraft(
                "owner",
                "owner",
                "laptop_2",
                ValueType.TEXT,
                "Dell",
                "dell",
                FreshnessClass.CHANGEABLE,
                Sensitivity.STANDARD,
            ),
            source("s3"),
        )
        stated = await service.refine(
            none_yet.assertion_id,
            SemanticAssertionDraft(
                "owner",
                "owner",
                "laptop_2",
                ValueType.TEXT,
                "Dell; bought 14 March 2023",
                "dell day",
                FreshnessClass.CHANGEABLE,
                Sensitivity.STANDARD,
                valid_from=known,
            ),
            source("s4"),
        )
        assert stated.valid_from == known
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_refine_refuses_identity_change_and_non_current_targets(
    tmp_path: Path,
) -> None:
    worker = worker_for(tmp_path / "refine-guard.db")
    service = service_for(worker)
    try:
        owned = await service.create(draft("Tigor", "tigor"), source("s1"))
        other = SemanticAssertionDraft(
            "owner",
            "owner",
            "another_predicate",
            ValueType.TEXT,
            "Tigor",
            "tigor",
            FreshnessClass.CHANGEABLE,
            Sensitivity.STANDARD,
        )
        with pytest.raises(MemoryLifecycleError, match="same subject and predicate"):
            await service.refine(owned.assertion_id, other, source("s2"))
        refined = await service.refine(
            owned.assertion_id, draft("Tigor diesel", "tigor d"), source("s3")
        )
        with pytest.raises(MemoryLifecycleError):
            await service.refine(
                owned.assertion_id, draft("Tigor petrol", "tigor p"), source("s4")
            )
        assert await current_ids(worker) == [refined.assertion_id]
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_change_with_unknown_effective_time_ends_current_ownership(
    tmp_path: Path,
) -> None:
    """A sale stated only as "last week": the owned row leaves the current
    view (by state), and neither validity boundary is invented."""
    worker = worker_for(tmp_path / "sold.db")
    service = service_for(worker)
    try:
        owned = await service.create(draft("Tigor owned", "owned"), source("s1"))
        sold = await service.historical_change(
            owned.assertion_id,
            draft("Tigor sold", "sold"),
            source("s2"),
            effective_at=None,
        )
        earlier = await service.get(owned.assertion_id)
        assert earlier.state is AssertionState.SUPERSEDED
        assert earlier.valid_to is None  # unknown, not the told time
        assert earlier.system_to == BASE
        assert sold.valid_from is None
        assert await current_ids(worker) == [sold.assertion_id]
        assert await operations(worker, sold.assertion_id) == [
            ("historical_change", None)
        ]
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_correct_still_retracts_unlike_refine(tmp_path: Path) -> None:
    worker = worker_for(tmp_path / "correct.db")
    service = service_for(worker)
    try:
        wrong = await service.create(draft("Jimny October", "oct"), source("s1"))
        fixed = await service.correct(
            wrong.assertion_id, draft("Jimny September", "sep"), source("s2")
        )
        assert (await service.get(wrong.assertion_id)).state is AssertionState.RETRACTED
        assert await operations(worker, fixed.assertion_id) == [("correct", None)]
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_forgetting_the_lineage_removes_refined_versions(tmp_path: Path) -> None:
    worker = worker_for(tmp_path / "forget.db")
    service = service_for(worker)
    try:
        owned = await service.create(draft("Classic 350", "c350"), source("s1"))
        refined = await service.refine(
            owned.assertion_id,
            draft("Classic 350 from 2021", "c350 2021"),
            source("s2"),
        )
        assert (
            await worker.run(
                lambda c: c.execute(
                    "SELECT count(*) FROM semantic_assertion WHERE predicate='test_preference'"
                ).fetchone()[0]
            )
            == 2
        )
        forgotten = await worker.run(
            lambda c: service._forget_sync(
                c,
                refined.assertion_id,
                source("s-forget"),
                "owner_forget",
                purge_lineage=True,
            )
        )
        assert forgotten
        rows = await worker.run(
            lambda c: c.execute(
                "SELECT count(*) FROM semantic_assertion WHERE predicate='test_preference'"
            ).fetchone()[0]
        )
        sources = await worker.run(
            lambda c: c.execute(
                "SELECT count(*) FROM memory_source WHERE source_id IN ('s1','s2')"
            ).fetchone()[0]
        )
        assert rows == 0 and sources == 0
    finally:
        await worker.close()
