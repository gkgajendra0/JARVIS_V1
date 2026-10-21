import asyncio
import sqlite3
from dataclasses import replace

import pytest

from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.query import CanonicalMemoryReader
from jarvis.memory.service import MemoryService
from jarvis.memory.types import Sensitivity
from jarvis.memory.worker import SerialConnectionWorker


@pytest.mark.asyncio
async def test_replay_has_one_canonical_effect(learning):
    first = await learning.service.admit_learning(learning.plan, learning.new_permit())
    second = await learning.service.admit_learning(learning.plan, learning.new_permit())
    assert first.status == "committed"
    assert second.status == "noop"
    assert await learning.canonical_effect_count() == 1
    assert await learning.count("personal_learning_receipt") == 1
    records = await learning.service.canonical_reader.learning_current()
    assert len(records) == 1 and records[0].value["state"] == "owned"
    assert records[0].sensitivity is Sensitivity.STANDARD


@pytest.mark.asyncio
async def test_unregistered_permit_and_mutated_payload_cannot_write(learning):
    permit = learning.new_permit()
    m = learning.plan.mutations[0]
    changed = replace(
        learning.plan,
        mutations=(replace(m, draft=replace(m.draft, value={"value": "Creta"})),),
    )
    with pytest.raises(PermissionError):
        await learning.service.admit_learning(changed, permit)
    with pytest.raises(PermissionError):
        await learning.service.admit_learning(learning.plan, object())
    assert await learning.count() == 0


@pytest.mark.asyncio
async def test_late_security_epoch_and_forged_source_are_denied(
    learning, authority_parts
):
    permit = learning.new_permit()
    forged = replace(learning.plan, source=replace(learning.source, runtime_id="other"))
    with pytest.raises(PermissionError):
        await learning.service.admit_learning(forged, permit)
    authority_parts.windows.lock_unlock()
    with pytest.raises(PermissionError):
        await learning.service.admit_learning(learning.plan, permit)
    assert await learning.count() == 0


@pytest.mark.asyncio
async def test_batch_rolls_back_every_effect_on_second_failure(learning, monkeypatch):
    second = replace(
        learning.plan.mutations[0],
        ordinal=1,
        predicate="owned_item_second",
        source=replace(learning.plan.mutations[0].source, source_id="second-source"),
        draft=replace(learning.plan.mutations[0].draft, predicate="owned_item_second"),
    )
    plan = replace(learning.plan, mutations=(*learning.plan.mutations, second))
    original = learning.lifecycle._insert_assertion

    def fail_second(*args, **kwargs):
        if kwargs["source_id"] == "second-source":
            raise RuntimeError("injected transaction failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(learning.lifecycle, "_insert_assertion", fail_second)
    with pytest.raises(RuntimeError, match="injected"):
        await learning.service.admit_learning(plan, learning.new_permit(plan))
    assert await learning.count() == 0
    assert await learning.count("personal_learning_receipt") == 0
    assert await learning.count("memory_source") == 0


@pytest.mark.asyncio
async def test_two_connections_cannot_replay_same_source(learning):
    def connect():
        c = sqlite3.connect(learning.path)
        c.execute("PRAGMA foreign_keys=ON")
        return c

    second_writer = SerialConnectionWorker(
        connect, thread_name="learning-second-writer"
    )
    other = MemoryService(
        MemoryLifecycleService(second_writer), CanonicalMemoryReader(learning.reader)
    )
    other.bind_learning_authority(learning.authority)
    try:
        results = await asyncio.gather(
            learning.service.admit_learning(learning.plan, learning.new_permit()),
            other.admit_learning(learning.plan, learning.new_permit()),
        )
        assert sorted(r.status for r in results) == ["committed", "noop"]
        assert await learning.count() == 1
    finally:
        await second_writer.close()


@pytest.mark.asyncio
async def test_epoch_race_denies_all_effects(learning):
    permit = learning.new_permit()
    await learning.writer.run(
        lambda c: (
            c.execute(
                "INSERT INTO personal_learning_suppression VALUES ('owned_item.vehicle',1,0,'now')"
            ),
            c.commit(),
        )
    )
    with pytest.raises(PermissionError, match="epoch"):
        await learning.service.admit_learning(learning.plan, permit)
    assert await learning.count() == 0


@pytest.mark.asyncio
async def test_expiry_during_write_rolls_back_receipts_and_assertions(
    learning, clock, monkeypatch
):
    original = learning.lifecycle._insert_assertion

    def delayed(*args, **kwargs):
        original(*args, **kwargs)
        clock.advance(31)

    monkeypatch.setattr(learning.lifecycle, "_insert_assertion", delayed)
    with pytest.raises(PermissionError):
        await learning.service.admit_learning(learning.plan, learning.new_permit())
    assert await learning.count() == 0
    assert await learning.count("personal_learning_receipt") == 0


@pytest.mark.asyncio
async def test_stale_exact_version_does_not_overwrite_explicit_change(learning):
    result = await learning.service.admit_learning(learning.plan, learning.new_permit())
    mutation = learning.plan.mutations[0]
    # A correction plans against a version that has already been superseded.
    changed = replace(mutation, action="correct", expected_assertion_id="old-version")
    plan = replace(learning.plan, mutations=(changed,))
    await learning.writer.run(
        lambda c: (c.execute("DELETE FROM personal_learning_receipt"), c.commit())
    )
    result = await learning.service.admit_learning(plan, learning.new_permit(plan))
    assert result.status == "stale"
    assert await learning.count() == 1
