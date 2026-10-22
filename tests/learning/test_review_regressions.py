"""Real temporary canonical DB regressions for whole-branch review findings."""

from dataclasses import replace
from uuid import uuid4

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import LearningBatch
from jarvis.memory.learning_reconciliation import LearningReconciler
from jarvis.memory.retrieval import SemanticRetrievalService
from jarvis.memory.types import AuthorityClass, MemorySourceClass
from jarvis.voice.personal_context import PersonalContextSession


def explicit_source(h):
    return replace(
        h.plan.mutations[0].source,
        source_id=str(uuid4()),
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
    )


@pytest.mark.asyncio
async def test_grant_context_and_resolver_cannot_read_outside_registered_categories(
    learning,
):
    await learning.service.remember_text(
        predicate="home city", value="Indore", source=explicit_source(learning)
    )
    await learning.service.remember_text(
        predicate="diet preference",
        value="vegetarian",
        source=explicit_source(learning),
    )
    catalog = await LearningReconciler(
        learning.service.canonical_reader, learning.authority
    ).catalog(
        learning.source, LearningBatch(candidates=[learning.candidate]), learning.grant
    )
    assert "Indore" not in str(catalog)
    c = ConversationSession()
    c.start()
    c.accept_turn(ConversationRole.USER, "What should I eat?")
    session = PersonalContextSession(
        conversation=c,
        retrieval=SemanticRetrievalService(learning.reader),
        authority=None,
        retire=lambda: None,
        learning_authority=learning.authority,
        learning_grant=learning.grant,
    )
    try:
        names = await session.catalog()
        assert "home_city" not in names["facets"]
        packet = await session.read(
            names["catalog_id"], [names["facets"].index("diet_preference")]
        )
        assert "vegetarian" in str(packet) and "Indore" not in str(packet)
    finally:
        session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("predicate", ["vehicle", "vehicles"])
async def test_legacy_vehicle_forget_blocks_future_automatic_vehicle_learning(
    learning, predicate
):
    await learning.service.remember_text(
        predicate=predicate, value="City", source=explicit_source(learning)
    )
    await learning.service.forget_exact(
        predicate=predicate, source=explicit_source(learning)
    )
    snapshot = await learning.service.learning_suppression()
    assert "owned_item.vehicle" in snapshot.suppressed
    with pytest.raises(PermissionError):
        await learning.service.admit_learning(learning.plan, learning.new_permit())


@pytest.mark.asyncio
async def test_reenable_rejects_fabricated_explicit_source_with_noop_guard(learning):
    with pytest.raises(PermissionError):
        await learning.service.reenable_learning_category(
            "owned_item.vehicle", explicit_source(learning), lambda: None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "Don't remember my vehicles",
        "Meri gaadiyan yaad mat rakhna",
        "मेरी गाड़ियाँ याद मत रखना",
    ],
)
async def test_category_veto_persists_without_provider_and_blocks_future_learning(
    learning, text
):
    import sqlite3
    from types import SimpleNamespace

    from jarvis.memory.learning_contracts import (
        EvidenceSpan,
        LearningResolution,
        LearningResolutionBatch,
    )
    from jarvis.memory.learning_runtime import PersonalLearningRuntime

    calls = []

    async def extract(source):
        calls.append(source.text)
        return LearningBatch(
            candidates=[
                learning.candidate.model_copy(
                    update={
                        "evidence": [
                            EvidenceSpan(turn_id=source.turn_id, start=8, end=12)
                        ]
                    }
                )
            ]
        )

    async def resolve(*args):
        return LearningResolutionBatch(
            resolutions=[LearningResolution(candidate_index=0, decision="new")]
        )

    r = PersonalLearningRuntime(
        learning.authority,
        learning.service,
        SimpleNamespace(extract=extract),
        SimpleNamespace(resolve=resolve),
        LearningReconciler(learning.service.canonical_reader, learning.authority),
        clock=lambda: 100,
    )
    c = ConversationSession()
    c.start()
    observe = r.bind(c, learning.grant)
    try:
        observe(c.accept_turn(ConversationRole.USER, text))
        await r.drain()
        assert not calls
        assert (
            "owned_item.vehicle"
            in (await learning.service.learning_suppression()).suppressed
        )
        with sqlite3.connect(learning.path) as db:
            assert db.execute(
                "SELECT suppressed FROM personal_learning_suppression WHERE category='owned_item.vehicle'"
            ).fetchone() == (1,)
        observe(c.accept_turn(ConversationRole.USER, "I own a City"))
        await r.drain()
        assert await learning.count() == 0
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_reenable_requires_exact_fresh_approval_and_invalidates_old_sources(
    learning, authority_parts
):
    await learning.service.remember_text(
        predicate="vehicles", value="City", source=explicit_source(learning)
    )
    await learning.service.forget_exact(
        predicate="vehicles", source=explicit_source(learning)
    )
    count = len(authority_parts.hello.calls)
    guard = learning.authority.authorize_reenable_category("owned_item.vehicle")
    assert len(authority_parts.hello.calls) == count + 1
    with pytest.raises(PermissionError):
        await learning.service.reenable_learning_category(
            "owned_item.device", explicit_source(learning), guard
        )
    await learning.service.reenable_learning_category(
        "owned_item.vehicle", explicit_source(learning), guard
    )
    assert not (await learning.service.learning_suppression()).suppressed
    with pytest.raises(PermissionError):
        await learning.service.reenable_learning_category(
            "owned_item.vehicle", explicit_source(learning), guard
        )
    with pytest.raises(PermissionError):
        await learning.service.admit_learning(learning.plan, learning.new_permit())
    authority_parts.hello.denied = True
    with pytest.raises(PermissionError):
        learning.authority.authorize_reenable_category("owned_item.device")
    authority_parts.hello.denied = False
    stale = learning.authority.authorize_reenable_category("owned_item.device")
    authority_parts.windows.lock_unlock()
    with pytest.raises(PermissionError):
        await learning.service.reenable_learning_category(
            "owned_item.device", explicit_source(learning), stale
        )


@pytest.mark.asyncio
async def test_privacy_controls_survive_full_queue_and_multiple_categories(learning):
    import asyncio

    from test_runtime import Extractor, conversation, runtime

    e = Extractor()
    r = runtime(learning, e)
    c = conversation()
    observe = r.bind(c, learning.grant)
    try:
        observe(c.accept_turn(ConversationRole.USER, "I own a City"))
        await e.entered.wait()
        for i in range(32):
            observe(c.accept_turn(ConversationRole.USER, f"I own device {i}"))
        observe(c.accept_turn(ConversationRole.USER, "Don't remember my vehicles"))
        observe(c.accept_turn(ConversationRole.USER, "Don't remember my devices"))
        e.release.set()
        await asyncio.wait_for(r.drain(), 2)
        assert (await learning.service.learning_suppression()).suppressed == frozenset(
            {"owned_item.vehicle", "owned_item.device"}
        )
        assert e.calls == 1 and not r._pending
    finally:
        await r.close()


def test_category_controls_do_not_promote_current_turn_or_quoted_veto():
    from jarvis.memory.learning_controls import category_veto

    for text in [
        "Don't remember this: my vehicles are City and Classic",
        "He said don't remember my vehicles",
        'I said "do not remember my vehicles"',
        "What if I say don't remember my vehicles?",
    ]:
        assert not category_veto(text)


@pytest.mark.asyncio
async def test_unrelated_records_do_not_exhaust_delegated_catalog_cap(learning):
    for i in range(40):
        await learning.service.remember_text(
            predicate=f"unrelated {i}",
            value="unrelated",
            source=explicit_source(learning),
        )
    await learning.service.remember_text(
        predicate="diet preference",
        value="vegetarian",
        source=explicit_source(learning),
    )
    records = await learning.service.canonical_reader.learning_current()
    assert [r.predicate for r in records] == ["diet_preference"]


@pytest.mark.asyncio
async def test_explicit_correction_of_learned_item_remains_in_delegated_scope(learning):
    await learning.service.admit_learning(learning.plan, learning.new_permit())
    predicate = learning.plan.mutations[0].predicate
    await learning.service.correct_text(
        predicate=predicate, value="Creta", source=explicit_source(learning)
    )
    records = await learning.service.canonical_reader.learning_current()
    assert len(records) == 1 and records[0].value == "Creta"
    catalog = await LearningReconciler(
        learning.service.canonical_reader, learning.authority
    ).catalog(
        learning.source, LearningBatch(candidates=[learning.candidate]), learning.grant
    )
    assert len(catalog.entries) == 1 and catalog.entries[0].category == "legacy"
    c = ConversationSession()
    c.start()
    c.accept_turn(ConversationRole.USER, "Which vehicle do I have?")
    session = PersonalContextSession(
        conversation=c,
        retrieval=SemanticRetrievalService(learning.reader),
        authority=None,
        retire=lambda: None,
        learning_authority=learning.authority,
        learning_grant=learning.grant,
    )
    try:
        names = await session.catalog()
        assert predicate in names["facets"]
        packet = await session.read(
            names["catalog_id"], [names["facets"].index(predicate)]
        )
        assert "Creta" in str(packet)
    finally:
        session.close()


@pytest.mark.asyncio
async def test_registered_scope_cannot_be_guessed_or_reused_after_forget(learning):
    await learning.service.remember_text(
        predicate="owned_item_forged",
        value="unrelated marker",
        source=explicit_source(learning),
    )
    assert not await learning.service.canonical_reader.learning_current()
    await learning.service.admit_learning(learning.plan, learning.new_permit())
    predicate = learning.plan.mutations[0].predicate
    await learning.service.correct_text(
        predicate=predicate, value="Creta", source=explicit_source(learning)
    )
    c = ConversationSession()
    c.start()
    c.accept_turn(ConversationRole.USER, "Which vehicle do I have?")
    session = PersonalContextSession(
        conversation=c,
        retrieval=SemanticRetrievalService(learning.reader),
        authority=None,
        retire=lambda: None,
        learning_authority=learning.authority,
        learning_grant=learning.grant,
    )
    try:
        names = await session.catalog()
        assert predicate in names["facets"]
        assert "owned_item_forged" not in names["facets"]
        await learning.service.forget_exact(
            predicate=predicate, source=explicit_source(learning)
        )
        await learning.service.remember_text(
            predicate=predicate,
            value="unrelated replacement",
            source=explicit_source(learning),
        )
        assert not await learning.service.canonical_reader.learning_current()
        packet = await session.read(
            names["catalog_id"], [names["facets"].index(predicate)]
        )
        assert "unrelated replacement" not in str(packet)
        assert not packet.get("facts")
    finally:
        session.close()
