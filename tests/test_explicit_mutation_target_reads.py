"""D17 (final acceptance, f6bd4972): target resolution for an explicit forget.

Recorded story-18 "Forget the Classic 350.": the catalog returned six opaque
facets; read [0] released one fact (Tata Tigor); the model then read [1],
[1], [2] and [3], one at a time, and every one returned invalid_selection.
No forget call and no consent request followed; the answer asked which
record to forget.

Cause: the legacy read path allowed one answer only one released set - any
later read with a different selection was refused - although its own comment
and the instructions describe a cumulative per-answer budget of four facts.
Facet names are opaque, so finding the item can take more than one read.
The read budget is now cumulative (at most four facts and 1,800 bytes per
answer, over one or several reads; released facts may be re-read). Beyond it
the read says read_budget_exhausted and the instructions say to ask.
"""

from __future__ import annotations

import pytest
import test_personal_context_runtime as fixtures

from jarvis.conversation import ConversationRole
from jarvis.memory.service import MemoryNotFoundError
from jarvis.voice.memory_tools import MemoryAgentTools

personal = fixtures.personal
source = fixtures.source

# Named so the catalog lists the three vehicles first and the plans after
# them, as in the recorded catalog (index 0 = Tata Tigor).
VEHICLES = {
    "a vehicle one": "Tata Tigor, sold",
    "a vehicle two": "Royal Enfield Classic 350",
    "a vehicle three": "Jimny",
}
PLANS = {
    "b plan one": "Rishikesh trip in October",
    "b plan two": "winter Spiti with the Jimny",
    "b plan three": "Goa, cancelled",
}


async def _story(personal, text="Forget the Classic 350."):
    session, service, conversation, authority, _ = personal
    for predicate, value in {**VEHICLES, **PLANS}.items():
        await service.remember_text(
            predicate=predicate, value=value, source=source(predicate)
        )
    conversation.accept_turn(ConversationRole.USER, text)
    catalog = await session.catalog()
    assert catalog["status"] == "available"
    return session, service, conversation, authority, catalog


def _index_naming(reads, needle):
    for index, result in reads:
        for fact in result.get("facts") or ():
            if needle in fact["text"]:
                return index
    return None


@pytest.mark.asyncio
async def test_recorded_sequence_now_reads_each_facet_and_reaches_the_forget(personal):
    session, service, conversation, authority, catalog = await _story(personal)
    assert catalog["facets"][:3] == [
        "a_vehicle_one",
        "a_vehicle_three",
        "a_vehicle_two",
    ]
    assert len(catalog["facets"]) >= 6  # opaque names, no values
    assert "Classic" not in str(catalog["facets"])
    reads = []
    for indices in ([0], [1], [1], [2], [3]):  # the recorded order
        result = await session.read(catalog["catalog_id"], indices)
        assert result["status"] == "selected", (indices, result)
        reads.append((indices[0], result))
    target = _index_naming(reads, "Classic 350")
    assert target is not None
    tools = MemoryAgentTools(service, conversation, personal_context=session)
    receipt = await tools.forget(
        predicate="Classic 350", catalog_id=catalog["catalog_id"], facet_index=target
    )
    assert receipt["ok"], receipt
    assert authority.calls[-1]["operation"] == "forget"  # consent was reached
    remaining = {
        p: (await service.inspect_exact(predicate=p)).record.value
        for p in {**VEHICLES, **PLANS}
        if p != "a vehicle two"
    }
    assert set(remaining.values()) == set(VEHICLES.values()) - {
        "Royal Enfield Classic 350"
    } | set(PLANS.values())
    with pytest.raises(MemoryNotFoundError):
        await service.inspect_exact(predicate="a vehicle two")


@pytest.mark.asyncio
async def test_one_answer_reads_at_most_four_facts_then_asks(personal):
    session, _service, _conversation, _authority, catalog = await _story(personal)
    for index in range(4):
        result = await session.read(catalog["catalog_id"], [index])
        assert result["status"] == "selected"
    over = await session.read(catalog["catalog_id"], [4])
    assert over["status"] == "invalid_selection"
    assert over["reason"] == "read_budget_exhausted" and over["not_read"] == [4]
    assert "ask the owner" in over["message"]
    again = await session.read(catalog["catalog_id"], [0, 2])  # already released
    assert again["status"] == "selected" and len(again["facts"]) == 2
    mixed = await session.read(catalog["catalog_id"], [1, 5])
    assert [f["predicate"] for f in mixed["facts"]] == [catalog["facets"][1]]
    assert mixed["reason"] == "read_budget_exhausted" and mixed["not_read"] == [5]


@pytest.mark.asyncio
async def test_a_single_call_still_reads_at_most_four(personal):
    session, _service, _conversation, _authority, catalog = await _story(personal)
    result = await session.read(catalog["catalog_id"], [0, 1, 2, 3])
    assert result["status"] == "selected" and len(result["facts"]) == 4
    assert (await session.read(catalog["catalog_id"], [4]))["reason"] == (
        "read_budget_exhausted"
    )


@pytest.mark.asyncio
async def test_declined_consent_deletes_nothing(personal):
    session, service, conversation, authority, catalog = await _story(personal)
    reads = [(i, await session.read(catalog["catalog_id"], [i])) for i in range(3)]
    target = _index_naming(reads, "Classic 350")
    approve = authority.authorize_personal_context

    def decline_forget(**kwargs):
        if kwargs.get("operation") == "forget":
            authority.calls.append(kwargs)
            raise PermissionError("declined")
        return approve(**kwargs)

    authority.authorize_personal_context = decline_forget
    tools = MemoryAgentTools(service, conversation, personal_context=session)
    with pytest.raises(PermissionError, match="consent was not granted"):
        await tools.forget(
            predicate="Classic 350",
            catalog_id=catalog["catalog_id"],
            facet_index=target,
        )
    assert authority.calls[-1]["operation"] == "forget"  # asked, declined
    assert (await service.inspect_exact(predicate="a vehicle two")).record.value == (
        "Royal Enfield Classic 350"
    )


@pytest.mark.asyncio
async def test_a_released_fact_that_changed_mid_answer_is_refused(personal):
    session, service, _conversation, _authority, catalog = await _story(personal)
    await session.read(catalog["catalog_id"], [0])
    first = catalog["facets"][0]
    predicate = next(p for p in {**VEHICLES, **PLANS} if p.replace(" ", "_") == first)
    await service.correct_text(predicate=predicate, value="changed", source=source("c"))
    assert (await session.read(catalog["catalog_id"], [0]))["status"] == "denied"
