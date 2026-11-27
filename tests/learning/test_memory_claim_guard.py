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
        ("I've saved your Jimny.", {"saved"}),
        ("I'll remember that.", {"saved"}),
        ("That's updated.", {"saved"}),
        ("I have forgotten the Classic 350.", {"forgotten"}),
        ("It's been removed.", {"forgotten"}),
        ("Theek hai, maine note kar liya.", {"saved"}),
        ("Yaad rakh liya.", {"saved"}),
        ("Maine woh hata diya.", {"forgotten"}),
        ("ठीक है, मैंने सेव कर लिया।", {"saved"}),
        # Not claims: negated, about the owner, questions answered, plain talk.
        ("I haven't saved that.", set()),
        ("Nothing was saved.", set()),
        ("Maine save nahi kiya.", set()),
        ("You told me you saved some money.", set()),
        ("Understood.", set()),
        ("Are you still deciding between the Thar and the Jimny?", set()),
        ("You sold the Tata Tigor last week.", set()),
    ],
)
def test_claims_are_affirmative_first_person_memory_changes(text, claims):
    assert memory_claims(text) == claims


def _op(operation, label=None):
    return SimpleNamespace(operation=operation, label=label)


def test_claims_must_be_backed_by_recorded_operations():
    assert unsupported_claims(D11_REPLY, ()) == {"saved"}
    assert unsupported_claims(D11_REPLY, [_op("change", "Goa")]) == set()
    assert unsupported_claims("I've forgotten it.", [_op("create")]) == {"forgotten"}
    assert unsupported_claims("I've forgotten it.", [_op("forget")]) == set()
    assert "nothing was saved" in correction_facts(())
    assert "change Goa" in correction_facts([_op("change", "Goa")])
    assert "still being processed" in correction_facts((), still_processing=True)


@pytest.mark.asyncio
async def test_receipts_wait_for_learning_and_report_only_what_happened():
    receipts = MemoryReceipts()
    receipts.learning_started("s1", "t1")
    assert receipts.view("s1", "t1")["status"] == "still_processing"
    assert await receipts.wait_learning("s1", "t1", 0.01) is False

    async def finish():
        await asyncio.sleep(0.01)
        receipts.learning_finished("s1", "t1", "committed", [("change", "Goa")])

    task = asyncio.create_task(finish())
    assert await receipts.wait_learning("s1", "t1", 1.0) is True
    await task
    view = receipts.view("s1", "t1")
    assert view["status"] == "saved"
    assert view["operations"] == [{"operation": "change", "item": "Goa"}]
    # A turn learning never started for: nothing will arrive, nothing saved.
    assert await receipts.wait_learning("s1", "t9", 1.0) is True
    assert receipts.view("s1", "t9")["status"] == "nothing_saved"
    receipts.explicit("s1", "t2", "forget", ("Classic 350",))
    assert receipts.view("s1", "t2")["status"] == "forgotten"
    receipts.learning_finished("s1", "t3", "no_eligible_fact")
    assert receipts.view("s1", "t3")["status"] == "nothing_saved"


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
    # Learning still running: "I've saved it" is not yet true, so it stops.
    assert check.stream_gate("Got it, I've saved") is True
    assert check.stream_gate("Got it") is False
    receipts.learning_finished(
        session, owner.turn_id, "committed", [("create", "Pixel 9")]
    )
    await asyncio.gather(*check._tasks)
    # The owner hears what memory recorded, from the record.
    assert delivered == [
        ("My new phone is a Pixel 9.", "only this was recorded: create Pixel 9")
    ]
    # Once recorded, the same claim streams freely (the correction itself).
    assert check.stream_gate("I've saved your Pixel 9.") is False
    await check.close()


@pytest.mark.asyncio
async def test_stream_gate_registry_is_per_session():
    class Session:
        pass

    session, other = Session(), Session()

    def gate(text):
        return True

    register_stream_gate(session, gate)
    assert stream_gate_for(session) is gate
    assert stream_gate_for(other) is None


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
        view = runtime.receipts.view(conversation.session_id, turn.turn_id)
        assert view["status"] == "saved"
        assert [o["operation"] for o in view["operations"]] == ["create"]
        cancel = conversation.accept_turn(ConversationRole.USER, "Cancel the Goa plan.")
        observe(cancel)  # the extractor proposes nothing (8ea0fd4e D11)
        await runtime.drain()
        assert (
            runtime.receipts.view(conversation.session_id, cancel.turn_id)["status"]
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
    assert (await tools.verified_memory_status(wait=0))["status"] == "nothing_saved"
    tools._record({"ok": True, "operation": "forget", "predicate": "classic 350"})
    tools._record({"ok": False, "operation": "remember", "predicate": "x"})
    status = await tools.verified_memory_status(wait=0)
    assert status["status"] == "forgotten"
    assert status["operations"] == [{"operation": "forget", "item": "classic 350"}]
    assert receipts.operations(conversation.session_id, turn.turn_id)
    # Without receipts the tool is not offered.
    plain = MemoryAgentTools(learning.service, conversation)
    assert len(plain.tools) == len(tools.tools) - 1
