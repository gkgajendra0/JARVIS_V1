"""A refused explicit memory change never commits through automatic learning.

Live voice acceptance, 27 Nov 2026 (session 48c472e1, turn d6e0274b):
diet_preference was vegan; the owner said "Okay. Correction. My diet
preference is vegetarian."; correct_memory asked for Windows Hello, which
was refused (17:48:14.295 "Fresh owner consent was not granted for this
request"), and 0.9 s later automatic learning committed the same correction
from the same turn.

An explicit request claims its owner turn before anything can fail; the
learning authority then refuses any write citing or quoting that turn (on
issue, before and inside the write transaction), and the learning runtime
drops its sources for it. In the voice runtime learning also holds its write
until the reply to the turn is over, so the claim is known first even when
learning is ready before the explicit tool is called.
"""

import asyncio
from types import SimpleNamespace

import pytest
from test_runtime import conversation, runtime

from jarvis.conversation import ConversationRole
from jarvis.memory.learning_contracts import (
    EvidenceSpan,
    LearningBatch,
    LearningCandidate,
    LearningResolution,
    LearningResolutionBatch,
)
from jarvis.memory.reply_settlement import ReplySettlement


class GatedFacts:
    """Proposes the fact as automatic learning would; can hold before it."""

    def __init__(self, *, gate=False):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        if not gate:
            self.release.set()

    async def extract(self, source):
        self.entered.set()
        await self.release.wait()
        return LearningBatch(
            candidates=[
                LearningCandidate(
                    category="owned_item",
                    kind="vehicle",
                    intent="new",
                    label="City",
                    value="City",
                    state="owned",
                    evidence=[EvidenceSpan(turn_id=source.turn_id, start=8, end=12)],
                )
            ]
        )


class New:
    async def resolve(self, *args):
        return LearningResolutionBatch(
            resolutions=[LearningResolution(candidate_index=0, decision="new")]
        )


async def _until(condition, seconds=5.0):
    for _ in range(int(seconds / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


def _runtime(learning, facts):
    r = runtime(learning, facts)
    r.resolver = New()
    return r


@pytest.mark.asyncio
async def test_explicit_claim_before_learning_starts_storage(learning):
    facts = GatedFacts(gate=True)
    r = _runtime(learning, facts)
    c = conversation()
    observe = r.bind(c, learning.grant)
    try:
        turn = c.accept_turn(ConversationRole.USER, "I own a City")
        observe(turn)
        await facts.entered.wait()
        # correct_memory claims the turn, then its consent is refused.
        learning.service.claim_explicit_request(
            session_id=c.session_id, turn_id=turn.turn_id
        )
        facts.release.set()
        await r.drain()
        assert await learning.count() == 0
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_learning_ready_first_waits_for_the_reply_and_then_sees_the_claim(
    learning,
):
    """Ordering reversed: learning is ready before the explicit tool is even
    called. It holds its write until the reply is over; the claim made during
    the reply wins."""
    r = _runtime(learning, GatedFacts())
    c = conversation()
    settlement = ReplySettlement()
    observe = r.bind(c, learning.grant, reply_settlement=settlement)
    try:
        turn = c.accept_turn(ConversationRole.USER, "I own a City")
        settlement.observe(turn)
        observe(turn)
        await _until(lambda: r._stage == "reply_settlement")
        assert await learning.count() == 0
        learning.service.claim_explicit_request(
            session_id=c.session_id, turn_id=turn.turn_id
        )
        settlement.observe(c.accept_turn(ConversationRole.ASSISTANT, "Okay."))
        await r.drain()
        assert await learning.count() == 0
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_without_an_explicit_request_learning_commits_after_the_reply(learning):
    r = _runtime(learning, GatedFacts())
    c = conversation()
    settlement = ReplySettlement()
    observe = r.bind(c, learning.grant, reply_settlement=settlement)
    try:
        turn = c.accept_turn(ConversationRole.USER, "I own a City")
        settlement.observe(turn)
        observe(turn)
        await _until(lambda: r._stage == "reply_settlement")
        settlement.observe(
            c.accept_turn(ConversationRole.ASSISTANT, "Nice, a Honda City.")
        )
        await r.drain()
        assert await learning.count() == 1
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_a_reply_that_never_settles_writes_nothing(learning):
    class Never:
        async def wait(self, turn_id, timeout):
            return False

    r = _runtime(learning, GatedFacts())
    c = conversation()
    observe = r.bind(c, learning.grant, reply_settlement=Never())
    try:
        observe(c.accept_turn(ConversationRole.USER, "I own a City"))
        await r.drain()
        assert await learning.count() == 0
        assert r.status().reason == "reply_not_settled"
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_a_claim_inside_the_write_window_is_refused_by_the_authority(learning):
    """In-flight race at the write boundary: a permit issued before the claim
    cannot be used after it."""
    permit = learning.new_permit()
    learning.authority.claim_explicit_request(learning.source.turn_id)
    with pytest.raises(PermissionError, match="explicit memory request"):
        await learning.service.admit_learning(learning.plan, permit)
    assert await learning.count() == 0
    with pytest.raises(PermissionError, match="explicit memory request"):
        learning.new_permit()


@pytest.mark.asyncio
async def test_the_explicit_requests_own_target_read_still_works(learning):
    """forget_memory/correct_memory find their target through a personal
    context read child of the same issuer, for the same (claimed) turn."""
    from dataclasses import replace

    learning.authority.claim_explicit_request(learning.source.turn_id)
    read = replace(learning.plan.binding(), operation="read")
    permit = learning.authority.issue_child(learning.grant, read)
    learning.authority.consume_read(permit)
    learning.authority.validate_read(permit)


@pytest.mark.asyncio
async def test_a_later_source_quoting_the_claimed_turn_is_refused_too(learning):
    first = learning.source
    learning.authority.claim_explicit_request(first.turn_id)
    later = SimpleNamespace(
        turn_id="later", turns=(*first.turns, SimpleNamespace(turn_id="later"))
    )
    assert learning.authority.explicitly_claimed(later)
    assert not learning.authority.explicitly_claimed(
        SimpleNamespace(turn_id="other", turns=(SimpleNamespace(turn_id="other"),))
    )


class _RefusingContext:
    """Personal context whose reservation (or consent) fails."""

    def reserve_mutation(self, operation):
        raise PermissionError("Fresh owner consent was not granted for this request")


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["correct", "forget"])
async def test_the_explicit_tool_claims_the_turn_before_anything_can_fail(
    learning, action
):
    from jarvis.memory.explicit import ExplicitMemoryAction
    from jarvis.voice.memory_tools import MemoryAgentTools

    c = conversation()
    turn = c.accept_turn(
        ConversationRole.USER, "Okay. Correction. My diet preference is vegetarian."
    )
    tools = MemoryAgentTools(learning.service, c)
    tools._personal_context = _RefusingContext()
    with pytest.raises(PermissionError):
        tools._change_turn(ExplicitMemoryAction(action))
    claimed = SimpleNamespace(turn_id=turn.turn_id, turns=(turn,))
    assert learning.authority.explicitly_claimed(claimed)


def test_reply_settlement_rules():
    c = conversation()
    settlement = ReplySettlement()

    async def settled(turn_id):
        return await settlement.wait(turn_id, 0.01)

    first = c.accept_turn(ConversationRole.USER, "one")
    settlement.observe(first)
    assert not asyncio.run(settled(first.turn_id))
    second = c.accept_turn(ConversationRole.USER, "two")
    settlement.observe(second)  # a newer owner turn settles the earlier one
    assert asyncio.run(settled(first.turn_id))
    assert not asyncio.run(settled(second.turn_id))
    assert not asyncio.run(settled("never-seen"))
    settlement.close()
    assert asyncio.run(settled(second.turn_id))


@pytest.mark.asyncio
async def test_claiming_one_turn_never_cancels_learning_for_another(learning):
    """Re-review: an explicit request on turn T2 must not cancel learning
    already running for T1."""
    facts = GatedFacts(gate=True)
    r = _runtime(learning, facts)
    c = conversation()
    observe = r.bind(c, learning.grant)
    try:
        first = c.accept_turn(ConversationRole.USER, "I own a City")
        observe(first)
        await facts.entered.wait()
        second = c.accept_turn(
            ConversationRole.USER, "Remember that my home city is Jaipur."
        )
        learning.service.claim_explicit_request(
            session_id=c.session_id, turn_id=second.turn_id
        )
        facts.release.set()
        await r.drain()
        assert await learning.count() == 1
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_a_reply_with_a_tool_step_settles_only_when_the_agent_listens():
    """A spoken segment before a tool call ("let me check") is accepted as an
    assistant turn while the agent is still thinking: not settled until the
    agent is back to listening, so correct_memory in the next generation
    claims the turn first."""
    c = conversation()
    settlement = ReplySettlement(agent_states=True)

    async def settled(turn_id):
        return await settlement.wait(turn_id, 0.01)

    turn = c.accept_turn(ConversationRole.USER, "Correction, I'm vegetarian.")
    settlement.observe(turn)
    settlement.agent_state("thinking")
    settlement.agent_state("speaking")
    settlement.observe(c.accept_turn(ConversationRole.ASSISTANT, "Let me check."))
    settlement.agent_state("thinking")  # tool call running
    assert not (await settled(turn.turn_id))
    settlement.agent_state("speaking")
    settlement.observe(c.accept_turn(ConversationRole.ASSISTANT, "Updated: diet."))
    assert not (await settled(turn.turn_id))
    settlement.agent_state("listening")
    assert await settled(turn.turn_id)


@pytest.mark.asyncio
async def test_memory_status_does_not_wait_for_the_turn_it_answers(learning):
    import time

    from jarvis.memory.memory_receipts import MemoryReceipts
    from jarvis.voice.memory_tools import MemoryAgentTools

    c = conversation()
    receipts = MemoryReceipts()
    fact = c.accept_turn(ConversationRole.USER, "I bought a Suzuki Jimny.")
    receipts.learning_finished(
        c.session_id, fact.turn_id, "committed", [("create", "Suzuki Jimny")]
    )
    question = c.accept_turn(ConversationRole.USER, "Did you save that?")
    receipts.learning_started(c.session_id, question.turn_id)  # held for the reply
    tools = MemoryAgentTools(learning.service, c, receipts=receipts)
    started = time.monotonic()
    status = await tools.verified_memory_status(wait=6.0)
    assert time.monotonic() - started < 1.0
    assert status["say"] == "Saved: Suzuki Jimny."
