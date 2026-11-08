"""Forgetting something by voice also removes the personal facts saved from it.

Live run 2026-11-08 (R2-C): "Our hotel is YAK and YETI." was saved in the
Nepal trip project AND learned as a personal fact (label "hotel"). "Now forget
the YAK and YETI hotel." removed only the saved conversation, yet Jarvis said
"that detail has been removed."

These tests use the real archive, real migrations (canonical personal memory
in the same database), the real lifecycle service to write facts the way
learning does, and the real history authority with a fake Windows Hello.
"""

import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import Wake, settle
from test_project_voice_fast_path import FastWake
from test_project_voice_forget_recall import ask_to_forget, texts

from jarvis.memory.assertions import SemanticAssertionDraft
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.provenance import MemorySource
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker
from jarvis.voice.project_voice import forget_confirmation

lab = project_voice_tests.lab


def _turn_id(lab, text):
    with sqlite3.connect(lab.db) as c:
        return c.execute(
            "SELECT event_id FROM conversation_event WHERE text=? AND role='user'",
            (text,),
        ).fetchone()[0]


async def _learn(lab, label, value, *, turn_id=None, receipt=True, predicate=None):
    """Save a personal fact the way personal learning does: source reference
    ``conversation:<session>:turn:<turn>`` plus a learning receipt."""
    now = datetime.now(UTC)
    ref = (
        f"conversation:{uuid4()}:turn:{turn_id}"
        if turn_id
        else f"local-control:test:{uuid4()}"
    )
    source = MemorySource(
        str(uuid4()),
        MemorySourceClass.OWNER_DIRECT,
        ref,
        now,
        AuthorityClass.OWNER_DIRECT,
        Sensitivity.STANDARD,
        now,
    )
    value_json = {
        "schema": "personal-learning-v1",
        "category": "event",
        "kind": "other",
        "label": label,
        "value": value,
    }
    draft = SemanticAssertionDraft(
        subject_scope="personal",
        subject="owner",
        predicate=predicate or f"event_{uuid4().hex}",
        value_type=ValueType.JSON,
        value=value_json,
        normalized_text=f"{label} {value}",
        freshness_class=FreshnessClass.CHANGEABLE,
        sensitivity=Sensitivity.STANDARD,
    )
    writer = SerialConnectionWorker(lambda: sqlite3.connect(lab.db), thread_name="l")
    try:
        record = await MemoryLifecycleService(writer).create(draft, source)
    finally:
        await writer.close()
    if turn_id and receipt:
        with sqlite3.connect(lab.db) as c:
            c.execute(
                "INSERT INTO personal_learning_receipt VALUES (?,?,?,?,?,?,?,?)",
                (
                    "runtime",
                    turn_id,
                    0,
                    "test",
                    "event",
                    "0" * 64,
                    source.source_id,
                    record.assertion_id,
                ),
            )
    return record.assertion_id


def _facts(lab):
    with sqlite3.connect(lab.db) as c:
        return {
            r[0]: r[1]
            for r in c.execute("SELECT assertion_id,value_json FROM semantic_assertion")
        }


async def _hotel_trip(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal trip", "Created project Nepal trip.")
    await wake.ask("Our hotel is YAK and YETI.", "Understood.")
    await wake.ask("We will take the Jimny.", "Noted.")
    wake.close()
    return voice


@pytest.mark.asyncio
async def test_forget_removes_the_personal_fact_learned_from_that_turn(
    lab, authority_parts
):
    voice = await _hotel_trip(lab)
    hotel = await _learn(
        lab,
        "hotel",
        "YAK and YETI",
        turn_id=_turn_id(lab, "Our hotel is YAK and YETI."),
    )
    vehicle = await _learn(
        lab, "vehicle", "Jimny", turn_id=_turn_id(lab, "We will take the Jimny.")
    )
    unrelated = await _learn(lab, "home city", "Pune")  # no conversation source
    wake = FastWake(voice)
    result = await ask_to_forget(
        wake, "Now forget the YAK and YETI hotel.", "YAK and YETI hotel"
    )
    await settle(voice)
    assert result["status"] == "forgotten", result
    assert result["personal_facts_removed"] == 1
    assert result["personal_facts_kept"] == 0
    facts = _facts(lab)
    assert hotel not in facts  # the learned hotel fact is gone
    assert {vehicle, unrelated} <= set(facts)  # unrelated personal facts kept
    assert not any("yeti" in t.casefold() for t in texts(lab))
    assert "We will take the Jimny." in texts(lab)
    # The confirmation says what was actually removed.
    assert "personal memory" in result["confirmation"]
    assert "kept" not in result["confirmation"]
    # The Hello approval showed the personal fact too.
    assert "1 personal memory entry ('hotel')" in repr(authority_parts.hello.calls[-1])
    with sqlite3.connect(lab.db) as c:
        assert not c.execute(
            "SELECT 1 FROM personal_learning_receipt WHERE target_id=?", (hotel,)
        ).fetchone()
        assert (
            c.execute(
                "SELECT count(*) FROM memory_operation WHERE target_id=? "
                "AND operation_type='forget' AND reason_code='conversation_forget'",
                (hotel,),
            ).fetchone()[0]
            == 1
        )
        assert not c.execute(
            "SELECT 1 FROM semantic_assertion_fts WHERE semantic_assertion_fts "
            "MATCH 'yeti'"
        ).fetchone()


@pytest.mark.asyncio
async def test_explicitly_saved_fact_from_that_turn_is_removed_without_a_receipt(lab):
    """An explicit "remember" save has the turn in its source reference only."""
    voice = await _hotel_trip(lab)
    hotel = await _learn(
        lab,
        "hotel",
        "YAK and YETI",
        turn_id=_turn_id(lab, "Our hotel is YAK and YETI."),
        receipt=False,
    )
    wake = FastWake(voice)
    result = await ask_to_forget(wake, "Forget the YAK and YETI hotel.", "YETI hotel")
    assert result["status"] == "forgotten"
    assert result["personal_facts_removed"] == 1
    assert hotel not in _facts(lab)


@pytest.mark.asyncio
async def test_an_orphan_fact_naming_the_words_is_removed_in_the_same_approval(
    lab, authority_parts
):
    """Live 2026-11-08: fact b66068f7 ("hotel: YAK and YETI") outlived the
    message it came from (forgotten earlier). A later forget naming it removes
    it in the same Windows Hello approval, which names it by label; a fact
    without every word is kept."""
    voice = await _hotel_trip(lab)
    orphan = await _learn(lab, "hotel", "YAK and YETI")  # no saved message
    other_hotel = await _learn(lab, "hotel", "Taj Lake Palace")
    approvals = len(authority_parts.hello.calls)
    wake = FastWake(voice)
    result = await ask_to_forget(wake, "Forget the YAK and YETI hotel.", "YETI hotel")
    assert result["status"] == "forgotten"
    assert result["personal_facts_removed"] == 1
    assert result["personal_facts_kept"] == 0
    facts = _facts(lab)
    assert orphan not in facts and other_hotel in facts
    assert len(authority_parts.hello.calls) == approvals + 1  # one approval
    assert "('hotel')" in repr(authority_parts.hello.calls[-1])
    assert "personal memory" in result["confirmation"]
    with sqlite3.connect(lab.db) as c:
        assert not c.execute(
            "SELECT 1 FROM personal_learning_suppression WHERE suppressed=1"
        ).fetchone()  # learning stays on: one fact forgotten, not a category


@pytest.mark.asyncio
async def test_words_matching_too_many_personal_facts_delete_none_of_them(lab):
    voice = await _hotel_trip(lab)
    ids = [await _learn(lab, "hotel", name) for name in ("A1", "B2", "C3", "D4")]
    wake = FastWake(voice)
    result = await ask_to_forget(wake, "Forget the hotel.", "hotel")
    assert result["status"] == "forgotten"
    assert result["personal_facts_removed"] == 0
    assert result["personal_facts_kept"] == 4
    assert set(ids) <= set(_facts(lab))
    assert "kept them" in result["confirmation"]
    assert "personal memory" not in result["confirmation"]


@pytest.mark.asyncio
async def test_only_label_and_value_words_count_not_schema_keys(lab):
    """'event' and 'state' are keys inside every learned fact's JSON: words in
    the owner's request must match the fact's own words."""
    voice = await _hotel_trip(lab)
    fact = await _learn(lab, "hotel", "YAK and YETI")
    wake = FastWake(voice)
    result = await ask_to_forget(wake, "Forget that event state.", "event state")
    assert result["status"] == "forgotten"
    assert result["personal_facts_removed"] == 0
    assert fact in _facts(lab)


@pytest.mark.asyncio
async def test_without_any_personal_fact_the_reply_claims_conversation_only(lab):
    voice = await _hotel_trip(lab)
    wake = FastWake(voice)
    result = await ask_to_forget(wake, "Forget the YAK and YETI hotel.", "YETI hotel")
    assert result["status"] == "forgotten"
    assert result["confirmation"] == "Done. I removed it from our saved conversations."
    assert "forget_memory" in result["guidance"]  # told NOT to call it now


@pytest.mark.asyncio
async def test_denied_hello_keeps_the_personal_fact(lab, authority_parts):
    voice = await _hotel_trip(lab)
    hotel = await _learn(
        lab,
        "hotel",
        "YAK and YETI",
        turn_id=_turn_id(lab, "Our hotel is YAK and YETI."),
    )
    wake = FastWake(voice)
    authority_parts.hello.denied = True
    result = await ask_to_forget(wake, "Forget the YAK and YETI hotel.", "YETI hotel")
    assert result["status"] == "not_forgotten"
    assert hotel in _facts(lab)


@pytest.mark.asyncio
async def test_fact_learned_after_the_preview_aborts_the_forget(
    lab, authority_parts, monkeypatch
):
    """The approval covers exactly what was shown: a fact saved from the same
    turns between preview and deletion changes the digest, nothing is deleted."""
    from jarvis.memory import project_controls

    voice = await _hotel_trip(lab)
    turn = _turn_id(lab, "Our hotel is YAK and YETI.")
    wake = FastWake(voice)
    original = project_controls.ProjectControls.forget_mentions

    async def late_learning(self, preview, **kwargs):
        await _learn(lab, "hotel", "YAK and YETI", turn_id=turn)
        return await original(self, preview, **kwargs)

    monkeypatch.setattr(
        project_controls.ProjectControls, "forget_mentions", late_learning
    )
    result = await ask_to_forget(wake, "Forget the YAK and YETI hotel.", "YETI hotel")
    assert result["status"] == "not_forgotten"
    assert any("YETI" in t for t in texts(lab))
    assert len(_facts(lab)) == 1


@pytest.mark.asyncio
async def test_canonical_forget_then_history_forget_reports_personal_memory(lab):
    receipt = SimpleNamespace(personal_facts=0, personal_mentions_kept=0)
    assert "personal memory" in forget_confirmation(receipt, canonical_already=True)
    assert "personal memory" not in forget_confirmation(receipt)
    two = SimpleNamespace(personal_facts=1, personal_mentions_kept=2)
    assert "2 saved personal facts also mention" in forget_confirmation(two)


@pytest.mark.asyncio
async def test_topic_checkpoint_from_the_forgotten_turn_is_removed(lab):
    voice = await _hotel_trip(lab)
    turn = _turn_id(lab, "Our hotel is YAK and YETI.")
    keep = _turn_id(lab, "We will take the Jimny.")
    with sqlite3.connect(lab.db) as c:
        c.execute(
            "INSERT INTO conversation_topic_checkpoint VALUES (?,?,?,?)",
            ("trip.hotel", turn, datetime.now(UTC).isoformat(), '{"h":1}'),
        )
        c.execute(
            "INSERT INTO conversation_topic_checkpoint VALUES (?,?,?,?)",
            ("trip.vehicle", keep, datetime.now(UTC).isoformat(), '{"v":1}'),
        )
    wake = FastWake(voice)
    result = await ask_to_forget(wake, "Forget the YAK and YETI hotel.", "YETI hotel")
    assert result["status"] == "forgotten"
    with sqlite3.connect(lab.db) as c:
        keys = {
            r[0]
            for r in c.execute("SELECT topic_key FROM conversation_topic_checkpoint")
        }
        tomb = {
            r[0]
            for r in c.execute("SELECT topic_key FROM conversation_topic_tombstone")
        }
    assert keys == {"trip.vehicle"}
    assert "trip.hotel" in tomb


@pytest.mark.asyncio
async def test_a_fact_whose_message_was_never_saved_is_removed_by_its_words(lab):
    voice = await _hotel_trip(lab)
    tea = await _learn(lab, "favourite tea", "Darjeeling")
    keep = await _learn(lab, "favourite coffee", "Coorg")
    wake = FastWake(voice)
    result = await ask_to_forget(wake, "Forget my Darjeeling tea.", "Darjeeling")
    assert result["status"] == "forgotten"
    assert result["personal_facts_removed"] == 1
    assert tea not in _facts(lab) and keep in _facts(lab)
