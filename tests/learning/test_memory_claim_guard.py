"""Jarvis never describes a memory change in its own words.

Receipts are written by the operations themselves (explicit tools on ok,
automatic learning when a turn finishes). The only memory statement Jarvis
may speak is a receipt sentence composed in code from them (memory_status or
an explicit tool's result), word for word. Anything else, true or not, is
stopped while it streams and replaced by the receipt (owner decision
2026-11-27). The recorded Paid lab 8ea0fd4e D11 reply ("Understood, I've
noted that the Goa plan is cancelled." while nothing was stored) is replayed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.memory_receipts import (
    NOTHING_SAVED,
    STILL_SAVING,
    MemoryReceipts,
    compose_say,
)
from jarvis.voice.memory_claims import (
    MemoryClaimCheck,
    memory_claims,
    register_stream_gate,
    stream_gate_for,
    unverified_statements,
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


def test_receipt_sentences_are_composed_from_the_record_only():
    assert compose_say(()) == NOTHING_SAVED
    assert compose_say((), still_processing=True) == STILL_SAVING
    ops = [
        _op("create", "Suzuki Jimny"),
        _op("create", "Pixel 9"),
        _op("change", "Goa plan"),
        _op("retract", "Classic 350"),
    ]
    assert compose_say(ops) == (
        "Saved: Suzuki Jimny; Pixel 9. Updated: Goa plan. Forgot: Classic 350."
    )
    assert compose_say([_op("create", "Pixel 9")], still_processing=True) == (
        "Saved: Pixel 9. Still saving the rest."
    )


def test_only_issued_receipt_sentences_may_state_a_memory_change():
    issued = ["Saved: Suzuki Jimny."]
    # Own words are never allowed, whether true or not (8ea0fd4e D11).
    assert unverified_statements(D11_REPLY, ()) == [D11_REPLY]
    assert unverified_statements("Yes, I've noted your Jimny.", issued)
    assert unverified_statements("Noted.", issued) == ["Noted."]
    # The receipt, word for word (case and punctuation aside), is allowed,
    # also around ordinary conversation.
    assert unverified_statements("Saved: Suzuki Jimny.", issued) == []
    assert (
        unverified_statements("Sure. saved, suzuki jimny! Anything else?", issued) == []
    )
    # A receipt-form sentence that differs from what was issued: wrong item,
    # extra item, or invented.
    assert unverified_statements("Saved: Mahindra Thar.", issued)
    assert unverified_statements("Saved: Suzuki Jimny and the Thar.", issued)
    assert unverified_statements("Forgot: Suzuki Jimny.", issued)
    # Still being spoken: only the start of an issued sentence passes.
    assert unverified_statements("Saved: Suzuki", issued) == []
    assert unverified_statements("Saved: Mahindra", issued)
    # A receipt verb after punctuation is a receipt-form statement too, and
    # the transcript of a spoken receipt may lose its colon.
    assert unverified_statements("Okay, saved: Goa plan.", issued)
    assert unverified_statements("Done — Saved: Goa plan.", issued)
    assert unverified_statements("Okay, saved, Suzuki Jimny.", issued) == []
    assert unverified_statements("Saved Suzuki Jimny.", issued) == []
    assert unverified_statements("You saved some money.", ()) == []
    # A finished reply is judged whole: a cut-off receipt is not a receipt.
    assert unverified_statements("Saved: Suzuki", issued, final=True)
    # Plain talk and "nothing was saved" are not memory claims.
    assert unverified_statements("Understood. Spiti in June sounds great.", ()) == []
    assert unverified_statements(NOTHING_SAVED, ()) == []


@pytest.mark.parametrize(
    "receipt",
    [
        "Saved: Suzuki Jimny.",
        "Saved: Suzuki Jimny; Pixel 9. Updated: Goa plan.",
        "Forgot: Classic 350.",
    ],
)
def test_an_issued_receipt_is_never_cut_while_it_streams(receipt):
    conversation, (owner,) = _conversation((ConversationRole.USER, "I bought a Jimny."))
    receipts = MemoryReceipts()
    receipts.issue(conversation.session_id, receipt, owner.turn_id)
    check, _ = _check(receipts, conversation)
    words = receipt.split()
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
    assert delivered == [("My new phone is a Pixel 9.", STILL_SAVING)]
    await check.close()


@pytest.mark.asyncio
async def test_recorded_d11_reply_is_replaced_by_the_receipt():
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
    assert delivered == [("Cancel the Goa plan.", NOTHING_SAVED)]
    # The receipt it was given is now allowed; corrected once per owner turn.
    assert NOTHING_SAVED in receipts.issued(conversation.session_id, owner.turn_id)
    check.observe(reply)
    await asyncio.gather(*check._tasks)
    assert len(delivered) == 1
    await check.close()


@pytest.mark.asyncio
async def test_a_true_claim_in_own_words_is_replaced_too_and_the_receipt_left_alone():
    """Item-level safety: a save of the Goa plan is real, but "I've updated
    the Goa plan as cancelled" is the model's wording, not the record's; the
    owner hears the receipt instead. The issued receipt itself passes."""
    conversation, (owner, own_words) = _conversation(
        (ConversationRole.USER, "Cancel the Goa plan."),
        (ConversationRole.ASSISTANT, "Done, I've updated the Goa plan in my memory."),
    )
    session = conversation.session_id
    receipts = MemoryReceipts()
    receipts.learning_finished(
        session, owner.turn_id, "committed", [("change", "Goa plan")]
    )
    check, delivered = _check(receipts, conversation)
    check.observe(own_words)
    await asyncio.gather(*check._tasks)
    assert delivered == [("Cancel the Goa plan.", "Updated: Goa plan.")]
    # The receipt itself, spoken for that request, passes.
    check.observe(
        conversation.accept_turn(ConversationRole.ASSISTANT, "Updated: Goa plan.")
    )
    check.observe(  # owner turns ignored
        conversation.accept_turn(ConversationRole.USER, "Thanks.")
    )
    await asyncio.gather(*check._tasks)
    assert len(delivered) == 1
    await check.close()


@pytest.mark.asyncio
async def test_while_streaming_own_words_are_stopped_then_the_receipt_is_spoken():
    conversation, (owner,) = _conversation(
        (ConversationRole.USER, "My new phone is a Pixel 9."),
    )
    session = conversation.session_id
    receipts = MemoryReceipts()
    receipts.learning_started(session, owner.turn_id)
    check, delivered = _check(receipts, conversation)
    assert check.stream_gate("Got it") is False
    assert check.stream_gate("Got it, noted") is True
    # Answered once per owner turn; later own words are still cut, with no
    # second correction.
    assert check.stream_gate("Got it, noted, the Pixel") is True
    receipts.learning_finished(
        session, owner.turn_id, "committed", [("create", "Pixel 9")]
    )
    await asyncio.gather(*check._tasks)
    assert delivered == [("My new phone is a Pixel 9.", "Saved: Pixel 9.")]
    await check.close()


@pytest.mark.asyncio
async def test_the_receipt_covers_the_recent_turns_did_you_save_that():
    """ "I bought a Jimny" (saved), then "Did you save that?": the receipt
    for the recent turns says what was saved, never more."""
    conversation, (first, second) = _conversation(
        (ConversationRole.USER, "I bought a Jimny."),
        (ConversationRole.USER, "Did you save that?"),
    )
    session = conversation.session_id
    receipts = MemoryReceipts()
    receipts.learning_finished(
        session, first.turn_id, "committed", [("create", "Suzuki Jimny")]
    )
    receipts.learning_started(session, second.turn_id)
    check, delivered = _check(receipts, conversation)
    assert check.stream_gate("Yes, I've noted your Thar.") is True
    receipts.learning_finished(session, second.turn_id, "no_eligible_fact")
    await asyncio.gather(*check._tasks)
    assert delivered == [("Did you save that?", "Saved: Suzuki Jimny.")]
    await check.close()


@pytest.mark.asyncio
async def test_the_reply_meant_to_read_the_receipt_is_checked_too():
    conversation, (owner,) = _conversation(
        (ConversationRole.USER, "Cancel the Goa plan.")
    )
    receipts = MemoryReceipts()
    receipts.learning_finished(
        conversation.session_id, owner.turn_id, "no_eligible_fact"
    )
    check, delivered = _check(receipts, conversation)
    assert check.stream_gate("Noted, the Goa plan is cancelled.") is True
    await asyncio.gather(*check._tasks)
    assert delivered == [("Cancel the Goa plan.", NOTHING_SAVED)]
    # The model's reply to the correction: own words again are cut, with no
    # second correction (no loop); the receipt itself passes.
    assert check.stream_gate("Okay, I've noted your Goa plan.") is True
    assert check.stream_gate("Nothing was saved from that.") is False
    await asyncio.gather(*check._tasks)
    assert len(delivered) == 1
    await check.close()


@pytest.mark.asyncio
async def test_a_receipt_is_valid_only_for_the_request_it_answered():
    conversation, (first,) = _conversation((ConversationRole.USER, "Plan Goa in May."))
    session = conversation.session_id
    receipts = MemoryReceipts()
    receipts.issue(session, "Saved: Goa plan.", first.turn_id)
    check, _ = _check(receipts, conversation)
    assert check.stream_gate("Saved: Goa plan.") is False
    conversation.accept_turn(ConversationRole.USER, "Forget my Goa plan.")
    # The earlier receipt cannot confirm the new request.
    assert check.stream_gate("Saved: Goa plan.") is True
    receipts.drop_issued(session)
    assert receipts.issued(session, first.turn_id) == ()
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
    status = await tools.verified_memory_status(wait=0)
    assert status["turns"][0]["status"] == "nothing_saved"
    assert status["say"] == NOTHING_SAVED
    result = tools._record(
        {"ok": True, "operation": "forget", "predicate": "classic 350"}
    )
    assert result["say"] == "Forgot: classic 350."
    failed = tools._record({"ok": False, "operation": "remember", "predicate": "x"})
    assert "say" not in failed
    status = await tools.verified_memory_status(wait=0)
    assert status["turns"][0]["status"] == "forgotten"
    assert status["turns"][0]["operations"] == [
        {"operation": "forget", "item": "classic 350"}
    ]
    assert status["say"] == "Forgot: classic 350."
    assert status["turns"][0]["turn"] == "latest"
    # Both receipts were issued: Jarvis may speak them word for word.
    issued = receipts.issued(conversation.session_id, turn.turn_id)
    assert issued[-1] == "Forgot: classic 350." and NOTHING_SAVED in issued
    assert receipts.operations(conversation.session_id, turn.turn_id)
    # Without receipts the tool is not offered.
    plain = MemoryAgentTools(learning.service, conversation)
    assert len(plain.tools) == len(tools.tools) - 1
