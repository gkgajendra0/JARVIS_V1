import asyncio
import threading
from dataclasses import replace

import pytest
from context_query_helpers import seed_item

from jarvis.memory.query import CanonicalMemoryReader
from jarvis.memory.retrieval import SemanticRetrievalService
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
)
from jarvis.personal_learning_scope import SUPPRESSION_KEYS


@pytest.mark.asyncio
async def test_snapshot_facade_contains_only_canonical_registered_current_scope(
    learning,
):
    await learning.service.admit_learning(learning.plan, learning.new_permit())
    original = (await learning.service.canonical_reader.learning_current())[0]
    await learning.service.correct_text(
        predicate=original.predicate,
        value="A corrected vehicle",
        source=replace(
            learning.plan.mutations[0].source,
            source_id="correction-source",
            source_class=MemorySourceClass.OWNER_EXPLICIT,
            authority_class=AuthorityClass.OWNER_EXPLICIT,
        ),
    )
    await seed_item(learning, "PRIVATE", sensitivity=Sensitivity.PRIVATE)
    await seed_item(learning, "LOCAL", sensitivity=Sensitivity.LOCAL_ONLY)
    await seed_item(learning, "TIMELY", freshness_class=FreshnessClass.TIME_SENSITIVE)
    await learning.service.remember_text(
        predicate="owned_item_forged",
        value="FORGED",
        source=replace(
            learning.plan.mutations[0].source,
            source_id="forged-source",
            source_class=MemorySourceClass.OWNER_EXPLICIT,
            authority_class=AuthorityClass.OWNER_EXPLICIT,
        ),
    )
    snapshot = await SemanticRetrievalService(
        learning.reader
    ).learning_context_snapshot()
    assert len(snapshot.entries) == 1
    assert snapshot.entries[0][0].value == "A corrected vehicle"
    assert snapshot.entries[0][0].normalized_text.endswith(": A corrected vehicle")
    assert snapshot.entries[0][1] == "owned_item.vehicle"
    assert snapshot.suppression == tuple(
        (k, 0, False) for k in sorted(SUPPRESSION_KEYS)
    )
    await learning.service.forget_exact(
        predicate=original.predicate,
        source=replace(
            learning.plan.mutations[0].source,
            source_id="forget-source",
            source_class=MemorySourceClass.OWNER_EXPLICIT,
            authority_class=AuthorityClass.OWNER_EXPLICIT,
        ),
    )
    assert not (
        await learning.service.canonical_reader.learning_context_snapshot()
    ).entries


@pytest.mark.asyncio
async def test_snapshot_preserves_32_record_limit_and_releases_savepoint_on_error(
    learning,
):
    for i in range(32):
        await seed_item(learning, f"item{i}")
    reader = CanonicalMemoryReader(learning.reader)
    assert len((await reader.learning_context_snapshot()).entries) == 32
    await seed_item(learning, "overflow")
    with pytest.raises(ValueError, match="overflow"):
        await reader.learning_context_snapshot()
    assert not await learning.reader.run(lambda c: c.in_transaction)


@pytest.mark.asyncio
async def test_snapshot_is_coherent_across_writer_commit(learning, monkeypatch):
    import jarvis.memory.query as module

    await learning.writer.run(lambda c: c.execute("PRAGMA journal_mode=WAL").fetchone())
    record = await seed_item(learning)
    ready, committed = threading.Event(), threading.Event()
    original = module._learning_current_scoped_sync

    def interleaved(connection):
        rows = original(connection)
        ready.set()
        assert committed.wait(3)
        return rows

    monkeypatch.setattr(module, "_learning_current_scoped_sync", interleaved)
    task = asyncio.create_task(
        CanonicalMemoryReader(learning.reader).learning_context_snapshot()
    )
    try:
        assert await asyncio.to_thread(ready.wait, 3)

        def update(connection):
            with connection:
                connection.execute(
                    "UPDATE semantic_assertion SET normalized_text='new' WHERE assertion_id=?",
                    (record.assertion_id,),
                )
                connection.execute(
                    "INSERT INTO personal_learning_suppression VALUES ('owned_item.vehicle',1,1,'fictional')"
                )

        await learning.writer.run(update)
    finally:
        committed.set()
    snapshot = await task
    assert snapshot.entries[0][0].normalized_text == "City; state=owned"
    assert ("owned_item.vehicle", 0, False) in snapshot.suppression
    assert (
        await learning.reader.run(
            lambda c: c.execute(
                "SELECT epoch FROM personal_learning_suppression"
            ).fetchone()[0]
        )
        == 1
    )
    assert not await learning.reader.run(lambda c: c.in_transaction)
