from dataclasses import replace
from uuid import uuid4

import pytest

from jarvis.memory.types import AuthorityClass, MemorySourceClass


def explicit_source(learning):
    return replace(
        learning.plan.mutations[0].source,
        source_id=str(uuid4()),
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
    )


@pytest.mark.asyncio
async def test_forget_purges_lineage_receipts_and_blocks_late_result(learning):
    first = learning.plan.mutations[0]
    other = replace(
        first,
        ordinal=1,
        predicate="owned_item_other",
        draft=replace(
            first.draft,
            predicate="owned_item_other",
            normalized_text="owned_item.vehicle: Creta; state=owned",
            value={**first.draft.value, "label": "Creta", "value": "Creta"},
        ),
        source=replace(first.source, source_id=str(uuid4())),
    )
    plan = replace(learning.plan, mutations=(first, other))
    await learning.service.admit_learning(plan, learning.new_permit(plan))
    await learning.service.correct_text(
        predicate=first.predicate,
        value="City corrected",
        source=explicit_source(learning),
    )
    assert await learning.count() == 3
    await learning.service.forget_exact(
        predicate=first.predicate, source=explicit_source(learning)
    )
    records = await learning.service.canonical_reader.learning_current()
    assert len(records) == 1 and records[0].predicate == other.predicate
    remaining = await learning.reader.run(
        lambda c: c.execute("SELECT predicate FROM semantic_assertion").fetchall()
    )
    assert remaining == [(other.predicate,)]
    assert await learning.count("personal_learning_receipt") == 1
    import sqlite3

    with sqlite3.connect(learning.path) as reopened:
        assert (
            reopened.execute(
                "SELECT count(*) FROM semantic_assertion_fts WHERE semantic_assertion_fts MATCH 'City'"
            ).fetchone()[0]
            == 0
        )
        assert (
            reopened.execute("SELECT count(*) FROM semantic_assertion").fetchone()[0]
            == 1
        )
    assert (
        await learning.reader.run(
            lambda c: c.execute(
                "SELECT count(*) FROM memory_source WHERE source_id=?",
                (first.source.source_id,),
            ).fetchone()[0]
        )
        == 0
    )
    state = await learning.service.learning_suppression()
    assert state.suppressed == frozenset({"owned_item.vehicle"})
    with pytest.raises(PermissionError):
        await learning.service.admit_learning(learning.plan, learning.new_permit())
    await learning.service.reenable_learning_category(
        "owned_item.vehicle", explicit_source(learning), lambda: None
    )
    state = await learning.service.learning_suppression()
    assert not state.suppressed and state.epochs["owned_item.vehicle"] == 2
    # An old receipt remains invalid even after explicit re-enable.
    with pytest.raises(PermissionError):
        await learning.service.admit_learning(learning.plan, learning.new_permit())


@pytest.mark.asyncio
async def test_reenable_needs_explicit_authority_and_guard(learning):
    with pytest.raises(PermissionError):
        await learning.service.reenable_learning_category(
            "owned_item.vehicle", learning.plan.mutations[0].source, lambda: None
        )
    with pytest.raises(PermissionError):
        await learning.service.reenable_learning_category(
            "owned_item.vehicle", explicit_source(learning), None
        )
