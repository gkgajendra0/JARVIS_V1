from __future__ import annotations

import asyncio
import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.memory.assertions import SemanticAssertionDraft
from jarvis.memory.lifecycle import MemoryLifecycleError, MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.provenance import MemorySource
from jarvis.memory.types import (
    AssertionState,
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
    VerificationState,
)
from jarvis.memory.worker import SerialConnectionWorker

BASE = datetime(2026, 9, 5, 6, 0, tzinfo=UTC)


def source(
    source_id: str,
    *,
    evidence_text: str | None = None,
) -> MemorySource:
    return MemorySource(
        source_id=source_id,
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        canonical_ref=f"conversation:session-1:{source_id}",
        observed_at=BASE,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
        sensitivity=Sensitivity.STANDARD,
        created_at=BASE,
        evidence_text=evidence_text,
    )


def draft(
    value: str,
    marker: str,
    *,
    valid_from: datetime | None = None,
) -> SemanticAssertionDraft:
    return SemanticAssertionDraft(
        subject_scope="owner",
        subject="owner",
        predicate="test_preference",
        value_type=ValueType.TEXT,
        value=value,
        normalized_text=marker,
        freshness_class=FreshnessClass.CHANGEABLE,
        sensitivity=Sensitivity.STANDARD,
        valid_from=valid_from,
    )


def id_factory(prefix: str):
    values = itertools.count(1)
    return lambda: f"{prefix}-{next(values)}"


def worker_for(path: Path) -> SerialConnectionWorker:
    def connection_factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    return SerialConnectionWorker(
        connection_factory,
        thread_name="jarvis-memory-lifecycle-test",
    )


def service_for(
    worker: SerialConnectionWorker,
    *,
    assertion_id_factory=None,
) -> MemoryLifecycleService:
    return MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=assertion_id_factory or id_factory("assertion"),
        operation_id_factory=id_factory("operation"),
    )


@pytest.mark.asyncio
async def test_create_historical_change_and_correction_have_distinct_semantics(
    tmp_path: Path,
) -> None:
    worker = worker_for(tmp_path / "lifecycle.db")
    service = service_for(worker)
    try:
        original_valid_from = datetime(2026, 9, 1, tzinfo=UTC)
        original = await service.create(
            draft("old", "markerold", valid_from=original_valid_from),
            source("source-create"),
        )
        change_at = datetime(2026, 9, 3, tzinfo=UTC)
        changed = await service.historical_change(
            original.assertion_id,
            draft("new", "markernew"),
            source("source-change"),
            effective_at=change_at,
        )

        old_after_change = await service.get(original.assertion_id)
        assert old_after_change is not None
        assert old_after_change.state is AssertionState.SUPERSEDED
        assert old_after_change.valid_to == change_at
        assert old_after_change.system_to == BASE
        assert await service.get_current(original.assertion_id) is None
        assert changed.state is AssertionState.ACTIVE
        assert changed.valid_from == change_at
        assert changed.supersedes_id == original.assertion_id

        corrected = await service.correct(
            changed.assertion_id,
            draft("corrected", "markercorrected"),
            source("source-correct"),
        )
        bad_after_correction = await service.get(changed.assertion_id)
        assert bad_after_correction is not None
        assert bad_after_correction.state is AssertionState.RETRACTED
        assert bad_after_correction.valid_to is None
        assert await service.get_current(changed.assertion_id) is None
        assert corrected.state is AssertionState.ACTIVE
        assert corrected.valid_from == change_at
        assert corrected.supersedes_id == changed.assertion_id
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_retract_verify_and_expire_are_separate_operations(
    tmp_path: Path,
) -> None:
    worker = worker_for(tmp_path / "states.db")
    service = service_for(worker)
    try:
        retract_target = await service.create(
            draft("wrong", "markerretract"),
            source("source-r-create"),
        )
        retracted = await service.retract(
            retract_target.assertion_id,
            source("source-retract"),
        )
        assert retracted.state is AssertionState.RETRACTED
        assert retracted.system_to == BASE
        assert retracted.valid_to is None

        verify_target = await service.create(
            draft("verify-me", "markerverify"),
            source("source-v-create"),
        )
        verified_at = datetime(2026, 9, 5, 6, 30, tzinfo=UTC)
        verified = await service.verify(
            verify_target.assertion_id,
            source("source-verify"),
            verified_at=verified_at,
        )
        assert verified.state is AssertionState.ACTIVE
        assert verified.verification_state is VerificationState.VERIFIED
        assert verified.last_verified_at == verified_at
        assert verified.value == "verify-me"
        assert verified.valid_from == verify_target.valid_from

        expire_target = await service.create(
            draft(
                "temporary",
                "markerexpire",
                valid_from=datetime(2026, 9, 4, tzinfo=UTC),
            ),
            source("source-e-create"),
        )
        expiry = datetime(2026, 9, 6, tzinfo=UTC)
        expired = await service.expire(
            expire_target.assertion_id,
            source("source-expire"),
            effective_at=expiry,
        )
        assert expired.state is AssertionState.EXPIRED
        assert expired.valid_to == expiry
        assert expired.system_to == BASE
        assert await service.get_current(expire_target.assertion_id) is None
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_forget_physically_purges_assertion_fts_and_prior_operations(
    tmp_path: Path,
) -> None:
    worker = worker_for(tmp_path / "forget.db")
    service = service_for(worker)
    shared_source = source("shared-source")
    try:
        forgotten = await service.create(
            draft("forget-value", "uniqueforgetmarker"),
            shared_source,
        )
        survivor = await service.create(
            draft("keep-value", "uniquekeepmarker"),
            shared_source,
        )

        assert await service.forget(
            forgotten.assertion_id,
            source("forget-command-source"),
        )
        assert await service.get(forgotten.assertion_id) is None
        assert await service.get_current(forgotten.assertion_id) is None
        assert await service.get_current(survivor.assertion_id) is not None

        forgotten_fts = await worker.run(
            lambda connection: connection.execute(
                "SELECT count(*) FROM semantic_assertion_fts "
                "WHERE semantic_assertion_fts MATCH 'uniqueforgetmarker'"
            ).fetchone()[0]
        )
        survivor_fts = await worker.run(
            lambda connection: connection.execute(
                "SELECT count(*) FROM semantic_assertion_fts "
                "WHERE semantic_assertion_fts MATCH 'uniquekeepmarker'"
            ).fetchone()[0]
        )
        assert forgotten_fts == 0
        assert survivor_fts == 1

        source_row = await worker.run(
            lambda connection: connection.execute(
                "SELECT evidence_text FROM memory_source WHERE source_id = 'shared-source'"
            ).fetchone()
        )
        assert source_row == (None,)

        operations = await worker.run(
            lambda connection: connection.execute(
                """
                SELECT operation_type, content_fingerprint
                FROM memory_operation
                WHERE target_id = ?
                ORDER BY occurred_at, operation_id
                """,
                (forgotten.assertion_id,),
            ).fetchall()
        )
        assert operations == [("forget", None)]
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_raw_source_evidence_text_is_rejected_and_rolled_back(
    tmp_path: Path,
) -> None:
    worker = worker_for(tmp_path / "raw-source.db")
    service = service_for(worker)
    try:
        with pytest.raises(MemoryLifecycleError, match="raw source evidence"):
            await service.create(
                draft("private", "rawmarker"),
                source("raw-source", evidence_text="do not copy this utterance"),
            )
        counts = await worker.run(
            lambda connection: (
                connection.execute("SELECT count(*) FROM memory_source").fetchone()[0],
                connection.execute(
                    "SELECT count(*) FROM semantic_assertion"
                ).fetchone()[0],
                connection.execute("SELECT count(*) FROM memory_operation").fetchone()[
                    0
                ],
            )
        )
        assert counts == (0, 0, 0)
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_mid_transition_failure_rolls_back_old_state_and_new_source(
    tmp_path: Path,
) -> None:
    worker = worker_for(tmp_path / "rollback.db")
    service = service_for(worker, assertion_id_factory=lambda: "same-assertion-id")
    try:
        original = await service.create(
            draft("old", "rollbackold"),
            source("rollback-create"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            await service.historical_change(
                original.assertion_id,
                draft("new", "rollbacknew"),
                source("rollback-change"),
                effective_at=datetime(2026, 9, 6, tzinfo=UTC),
            )

        restored = await service.get_current(original.assertion_id)
        assert restored is not None
        assert restored.state is AssertionState.ACTIVE
        assert restored.valid_to is None
        assert restored.system_to is None
        new_source_count = await worker.run(
            lambda connection: connection.execute(
                "SELECT count(*) FROM memory_source WHERE source_id = 'rollback-change'"
            ).fetchone()[0]
        )
        assert new_source_count == 0
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_concurrent_callers_are_serialized_through_lifecycle_writer(
    tmp_path: Path,
) -> None:
    worker = worker_for(tmp_path / "concurrent.db")
    service = service_for(worker)
    shared = source("concurrent-shared")
    try:
        records = await asyncio.gather(
            *(
                service.create(draft(f"value-{index}", f"marker{index}"), shared)
                for index in range(20)
            )
        )
        assert len({record.assertion_id for record in records}) == 20
        counts = await worker.run(
            lambda connection: (
                connection.execute(
                    "SELECT count(*) FROM semantic_assertion"
                ).fetchone()[0],
                connection.execute("SELECT count(*) FROM memory_operation").fetchone()[
                    0
                ],
                connection.execute("SELECT count(*) FROM memory_source").fetchone()[0],
            )
        )
        assert counts == (20, 20, 1)
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_multilingual_values_round_trip_without_lifecycle_special_cases(
    tmp_path: Path,
) -> None:
    worker = worker_for(tmp_path / "multilingual.db")
    service = service_for(worker)
    values = (
        ("I prefer mountain drives", "englishmountain"),
        ("मुझे पहाड़ पसंद हैं", "हिंदीपहाड़"),
        ("Mujhe pahadon mein drive pasand hai", "hinglishpahad"),
    )
    try:
        records = []
        for index, (value, marker) in enumerate(values):
            records.append(
                await service.create(
                    draft(value, marker),
                    source(f"multilingual-{index}"),
                )
            )
        assert [record.value for record in records] == [item[0] for item in values]
        assert [record.normalized_text for record in records] == [
            item[1] for item in values
        ]
    finally:
        await worker.close()
