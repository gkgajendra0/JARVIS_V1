"""A reply may say memory changed only when memory verifiably changed.

Receipts are written by the operations themselves (explicit tools on ok,
automatic learning when a turn finishes); memory_status reads them; a reply
that claims a change the receipts do not support is stopped while it streams
(when learning has not confirmed it yet) and corrected from the record. The
recorded Paid lab 8ea0fd4e D11 reply ("Understood, I've noted that the Goa
plan is cancelled." while nothing was stored) is replayed.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.memory_receipts import MemoryReceipts
from jarvis.voice.memory_claims import (
    MemoryClaimCheck,
    correction_facts,
    memory_claims,
    register_stream_gate,
    stream_gate_for,
    unsupported_claims,
)

D11_REPLY = "Understood, I've noted that the Goa plan is cancelled."


@pytest.mark.parametrize(
    ("text", "claims"),
    [
        (D11_REPLY, {"saved"}),
        ("Noted.", {"saved"}),
        ("Got it, noted — Jimny for Spiti.", {"saved"}),
        ("I'll remember that.", {"saved"}),
        ("That's noted.", {"saved"}),
        ("I've added it to your memory.", {"saved"}),
        ("Noted, I won't forget that.", {"saved"}),
        ("I have forgotten the Classic 350.", {"forgotten"}),
        ("I've removed it from your memory.", {"forgotten"}),
        ("Theek hai, maine note kar liya.", {"saved"}),
        ("Yaad rakh liya.", {"saved"}),
        ("Maine woh memory se hata diya.", {"forgotten"}),
        ("ठीक है, मैंने नोट कर लिया।", {"saved"}),
        # Other tools' actions are never memory claims.
        ("I've saved the document in Notepad.", set()),
        ("I've added the task to your Goa project.", set()),
        ("I've updated the file.", set()),
        ("Done, I've changed the volume.", set()),
        ("That's been recorded in the spreadsheet.", set()),
        # Negated, about the owner, questions, plain talk.
        ("I haven't noted that.", set()),
        ("Nothing was saved.", set()),
        ("Maine note nahi kiya.", set()),
        ("You told me you saved some money.", set()),
        ("Understood.", set()),
        ("Are you still deciding between the Thar and the Jimny?", set()),
        ("You sold the Tata Tigor last week.", set()),
        # Ordinary speech that only sounds like memory (re-review 109123cf).
        ("Sorry, I forgot to mention the meeting is at 3.", set()),
        ("I forget, was it Tuesday?", set()),
        ("I'll remember to remind you tomorrow.", set()),
        ("I've stored it in my notes app.", set()),
        ("I have updated the records in Excel.", set()),
        # A negation after the claim belongs to the fact, not the claim.
        ("I'll remember that you can't eat peanuts.", {"saved"}),
        ("I've noted that you don't drink coffee.", {"saved"}),
    ],
)
def test_claims_are_affirmative_first_person_memory_changes(text, claims):
    assert memory_claims(text) == claims


def _op(operation, label=None, turn_id="t1"):
    return SimpleNamespace(operation=operation, label=label, turn_id=turn_id)


def test_claims_must_be_backed_by_the_record():
    # Nothing recorded: every claim is unsupported (8ea0fd4e D11).
    assert unsupported_claims(D11_REPLY, (), newest="t1") == {"saved"}
    assert unsupported_claims("Noted.", (), newest="t1") == {"saved"}
    # An operation of the claimed kind on the newest owner turn backs it.
    assert unsupported_claims(D11_REPLY, [_op("change", "Goa")], newest="t1") == set()
    assert (
        unsupported_claims("Noted.", [_op("create", "Pixel 9")], newest="t1") == set()
    )
    # A withdrawal never backs a save claim, nor a save a forget claim.
    assert unsupported_claims(
        "I've noted your Jimny.", [_op("retract", "Classic 350")], newest="t1"
    ) == {"saved"}
    assert unsupported_claims(
        "I have forgotten the Classic 350.", [_op("create", "Classic 350")], newest="t1"
    ) == {"forgotten"}
    # An earlier turn's save backs only a sentence that names its item,
    # and a bare "Noted." never: it answers the newest turn.
    earlier = [_op("create", "Jimny", turn_id="t0")]
    assert unsupported_claims("Yes, I've noted your Jimny.", earlier, "t1") == set()
    assert unsupported_claims("Noted.", earlier, newest="t1") == {"saved"}
    assert unsupported_claims("Noted: you prefer window seats.", earlier, "t1") == {
        "saved"
    }
    # While a sentence is still being spoken its item may come later.
    assert unsupported_claims("Yes, I've noted that you", earlier, "t1") == set()
    assert unsupported_claims("Yes, I've noted that you", (), "t1") == {"saved"}
    assert "nothing was saved" in correction_facts(())
    assert "change Goa" in correction_facts([_op("change", "Goa")])
    assert "still being processed" in correction_facts((), still_processing=True)


@pytest.mark.parametrize(
    "reply",
    [
        "Yes, I've noted that you bought a Jimny.",
        "I'll remember that for next time.",
        "Got it, noted, your new car is the Jimny.",
    ],
)
def test_a_verified_confirmation_is_never_cut_while_it_streams(reply):
    conversation, (owner,) = _conversation((ConversationRole.USER, "I bought a Jimny."))
    receipts = MemoryReceipts()
    receipts.learning_finished(
        conversation.session_id, owner.turn_id, "committed", [("create", "Jimny")]
    )
    check, _ = _check(receipts, conversation)
    words = reply.split()
    assert not any(
        check.stream_gate(" ".join(words[:n])) for n in range(1, len(words) + 1)
    )


@pytest.mark.asyncio
async def test_receipts_wait_for_learning_and_report_only_what_happened():
    receipts = MemoryReceipts()
    receipts.learning_started("s1", "t1")
    assert receipts.view("s1", ["t1"])["turns"][0]["status"] == "still_processing"
    assert await receipts.wait_learning("s1", "t1", 0.01) is False

    async def finish():
        await asyncio.sleep(0.01)
        receipts.learning_finished("s1", "t1", "committed", [("change", "Goa")])

    task = asyncio.create_task(finish())
    assert await receipts.wait_learning("s1", ("t1",), 1.0) is True
    await task
    (entry,) = receipts.view("s1", ["t1"])["turns"]
    assert entry["status"] == "saved"
    assert entry["operations"] == [{"operation": "change", "item": "Goa"}]
    # A turn learning never started for: nothing will arrive, nothing saved.
    assert await receipts.wait_learning("s1", "t9", 1.0) is True
    assert receipts.view("s1", ["t9"])["turns"][0]["status"] == "nothing_saved"
    receipts.explicit("s1", "t2", "forget", ("Classic 350",))
    assert receipts.view("s1", ["t2"])["turns"][0]["status"] == "forgotten"
    receipts.learning_finished("s1", "t3", "no_eligible_fact")
    assert receipts.view("s1", ["t3"])["turns"][0]["status"] == "nothing_saved"


@pytest.mark.asyncio
async def test_a_turn_with_two_learning_sources_finishes_after_both():
    receipts = MemoryReceipts()
    receipts.learning_started("s1", "t1")
    receipts.learning_started("s1", "t1")
    receipts.learning_finished("s1", "t1", "no_change")
    assert receipts.pending("s1", "t1")
    receipts.learning_finished("s1", "t1", "committed", [("create", "Pixel 9")])
    assert not receipts.pending("s1", "t1")
    assert await receipts.wait_learning("s1", "t1", 0.1) is True


def _conversation(*turns):
    conversation = ConversationSession()
    conversation.start()
    out = [conversation.accept_turn(role, text) for role, text in turns]
    return conversation, out


def _check(receipts, conversation, *, idle=lambda: True):
    delivered = []

    async def deliver(owner_words, facts):
        delivered.append((owner_words, facts))
        return True

    check = MemoryClaimCheck(
        receipts,
        conversation,
        deliver,
        idle=idle,
        learning_wait=1.0,
        idle_wait=1.0,
        poll=0.01,
    )
    return check, delivered


@pytest.mark.asyncio
async def test_cut_speech_is_always_answered_even_if_learning_never_finishes():
    conversation, (owner,) = _conversation(
        (ConversationRole.USER, "My new phone is a Pixel 9."),
    )
    receipts = MemoryReceipts()
    receipts.learning_started(conversation.session_id, owner.turn_id)
    check, delivered = _check(receipts, conversation)
    check.learning_wait = 0.05
    assert check.stream_gate("Noted, the Pixel 9.") is True
    await asyncio.gather(*check._tasks)
    assert delivered == [
        (
            "My new phone is a Pixel 9.",
            "your request is still being processed and nothing is saved yet",
        )
    ]
    await check.close()


@pytest.mark.asyncio
async def test_recorded_d11_reply_is_corrected_from_the_record():
    conversation, (owner, reply) = _conversation(
        (ConversationRole.USER, "Cancel the Goa plan."),
        (ConversationRole.ASSISTANT, D11_REPLY),
    )
    receipts = MemoryReceipts()
    # 8ea0fd4e: learning ran and proposed nothing.
    receipts.learning_started(conversation.session_id, owner.turn_id)
    receipts.learning_finished(
        conversation.session_id, owner.turn_id, "no_eligible_fact"
    )
    check, delivered = _check(receipts, conversation)
    check.observe(reply)
    await asyncio.gather(*check._tasks)
    assert delivered == [
        (
            "Cancel the Goa plan.",
            "nothing was saved, changed or forgotten for that request",
        )
    ]
    # Corrected once per owner turn.
    check.observe(reply)
    await asyncio.gather(*check._tasks)
    assert len(delivered) == 1
    await check.close()


@pytest.mark.asyncio
async def test_a_backed_claim_and_a_plain_reply_are_left_alone():
    conversation, (owner, reply) = _conversation(
        (ConversationRole.USER, "Cancel the Goa plan."),
        (ConversationRole.ASSISTANT, "Done, I've updated the Goa plan as cancelled."),
    )
    receipts = MemoryReceipts()
    receipts.learning_finished(
        conversation.session_id, owner.turn_id, "committed", [("change", "Goa")]
    )
    check, delivered = _check(receipts, conversation)
    check.observe(reply)
    check.observe(
        conversation.accept_turn(ConversationRole.USER, "Thanks.")
    )  # owner turns ignored
    await asyncio.gather(*check._tasks)
    assert delivered == []
    await check.close()


@pytest.mark.asyncio
async def test_while_streaming_an_unconfirmed_claim_is_stopped_then_the_record_is_told():
    conversation, (owner,) = _conversation(
        (ConversationRole.USER, "My new phone is a Pixel 9."),
    )
    session = conversation.session_id
    receipts = MemoryReceipts()
    receipts.learning_started(session, owner.turn_id)
    check, delivered = _check(receipts, conversation)
    assert check.stream_gate("Got it") is False
    # Learning still running: "noted" is not yet true, so it stops.
    assert check.stream_gate("Got it, noted") is True
    # Stopped and answered once per owner turn; later speech is not cut.
    assert check.stream_gate("Got it, noted, the Pixel") is False
    receipts.learning_finished(
        session, owner.turn_id, "committed", [("create", "Pixel 9")]
    )
    await asyncio.gather(*check._tasks)
    # The owner hears what memory recorded, from the record.
    assert delivered == [
        ("My new phone is a Pixel 9.", "only this was recorded: create Pixel 9")
    ]
    await check.close()


@pytest.mark.asyncio
async def test_a_claim_about_an_earlier_turn_is_judged_on_that_turn():
    """ "I bought a Jimny" (saved), then "Did you save that?": the answer
    "Yes, I've noted your Jimny." is backed by the earlier turn's record."""
    conversation, (first, second) = _conversation(
        (ConversationRole.USER, "I bought a Jimny."),
        (ConversationRole.USER, "Did you save that?"),
    )
    session = conversation.session_id
    receipts = MemoryReceipts()
    receipts.learning_finished(
        session, first.turn_id, "committed", [("create", "Jimny")]
    )
    receipts.learning_started(session, second.turn_id)
    check, delivered = _check(receipts, conversation)
    assert check.stream_gate("Yes, I've noted your Jimny.") is False
    # A claim about something never saved is still stopped.
    assert check.stream_gate("Yes, I've noted your Thar.") is True
    receipts.learning_finished(session, second.turn_id, "no_eligible_fact")
    await asyncio.gather(*check._tasks)
    assert delivered and "nothing was saved" in delivered[0][1]
    await check.close()


def test_stream_gate_rides_on_the_session_and_is_removed_on_close():
    from jarvis.voice.memory_claims import unregister_stream_gate

    class Session:
        pass

    session, other = Session(), Session()

    def gate(text):
        return True

    register_stream_gate(session, gate)
    assert stream_gate_for(session) is gate
    assert stream_gate_for(other) is None
    unregister_stream_gate(session, gate)
    assert stream_gate_for(session) is None


@pytest.mark.asyncio
async def test_learning_runtime_records_what_each_turn_committed(learning):
    from test_slice1_d9_clarification import (  # noqa: F401
        CHOICE,
        MatchPlan,
        Script,
        _choice,
        lab,
    )

    from jarvis.memory.learning_reconciliation import LearningReconciler
    from jarvis.memory.learning_runtime import PersonalLearningRuntime

    script, resolver = Script(), MatchPlan()
    runtime = PersonalLearningRuntime(
        learning.authority,
        learning.service,
        script,
        resolver,
        LearningReconciler(learning.service.canonical_reader, learning.authority),
        clock=lambda: 100,
    )
    conversation = ConversationSession()
    conversation.start()
    observe = runtime.bind(conversation, learning.grant)
    try:
        script.by_text[CHOICE] = _choice()
        turn = conversation.accept_turn(ConversationRole.USER, CHOICE)
        observe(turn)
        assert runtime.receipts.pending(conversation.session_id, turn.turn_id)
        await runtime.drain()
        (entry,) = runtime.receipts.view(conversation.session_id, [turn.turn_id])[
            "turns"
        ]
        assert entry["status"] == "saved"
        assert [o["operation"] for o in entry["operations"]] == ["create"]
        cancel = conversation.accept_turn(ConversationRole.USER, "Cancel the Goa plan.")
        observe(cancel)  # the extractor proposes nothing (8ea0fd4e D11)
        await runtime.drain()
        assert (
            runtime.receipts.view(conversation.session_id, [cancel.turn_id])["turns"][
                0
            ]["status"]
            == "nothing_saved"
        )
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_explicit_tools_record_receipts_and_memory_status_reads_them(learning):
    from jarvis.voice.memory_tools import MemoryAgentTools

    conversation = ConversationSession()
    conversation.start()
    turn = conversation.accept_turn(ConversationRole.USER, "Forget the Classic 350.")
    receipts = MemoryReceipts()
    tools = MemoryAgentTools(learning.service, conversation, receipts=receipts)
    assert tools.memory_status in tools.tools
    status = await tools.verified_memory_status(wait=0)
    assert status["turns"][0]["status"] == "nothing_saved"
    tools._record({"ok": True, "operation": "forget", "predicate": "classic 350"})
    tools._record({"ok": False, "operation": "remember", "predicate": "x"})
    status = await tools.verified_memory_status(wait=0)
    assert status["turns"][0]["status"] == "forgotten"
    assert status["turns"][0]["operations"] == [
        {"operation": "forget", "item": "classic 350"}
    ]
    assert status["turns"][0]["turn"] == "latest"
    assert "Classic 350" not in json.dumps(status["rule"])
    assert receipts.operations(conversation.session_id, turn.turn_id)
    # Without receipts the tool is not offered.
    plain = MemoryAgentTools(learning.service, conversation)
    assert len(plain.tools) == len(tools.tools) - 1
