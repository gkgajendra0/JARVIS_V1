"""Request-bound explicit changes, and ending a private wake for an
unverified speaker (owner review of ad87660a, 28 Nov 2026).

1. An explicit memory change acts for its originating request: the owner turn
   bound by the first tool call of the reply (target resolution), not
   whichever turn is latest when the mutation tool runs. If another utterance
   arrives between target resolution and the mutation call, nothing changes:
   the original request is claimed (excluded from automatic learning) and the
   change is refused before any consent prompt.

2. Once owner-private context is in the live model context, a request that
   cannot be positively verified as the owner (non-owner, unknown, timeout,
   barge-in) ends and clears the wake, interrupting speech in flight. A wake
   that released nothing private is unaffected.
"""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_background_speech_replay import _FakeAudio, _mark_session_ready, _session_pair
from test_explicit_request_learning_isolation import GatedFacts, _runtime
from test_runtime import conversation

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationRole
from jarvis.memory.explicit import ExplicitMemoryAction
from jarvis.memory.reply_settlement import ReplySettlement
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.voice.memory_tools import (
    ExplicitMemoryAuthorizationError,
    MemoryAgentTools,
)


def _claimed(learning, turn):
    return learning.authority.explicitly_claimed(
        SimpleNamespace(turn_id=turn.turn_id, turns=(turn,))
    )


@pytest.mark.asyncio
async def test_an_utterance_between_target_resolution_and_mutation_changes_nothing(
    learning,
):
    """Exact regression: "Correction, my diet is vegetarian" (T); target
    resolution binds T; "hmm" (T2) is accepted while the reply is still
    running; correct_memory runs. The change is refused before consent, T is
    claimed (not T2), and T's correction never commits through learning."""
    facts = GatedFacts()
    r = _runtime(learning, facts)
    c = conversation()
    settlement = ReplySettlement(agent_states=True)
    settlement.agent_state("listening")
    observe = r.bind(c, learning.grant, reply_settlement=settlement)
    try:
        request = c.accept_turn(ConversationRole.USER, "I own a City")
        settlement.observe(request)
        observe(request)
        settlement.agent_state("thinking")
        assert settlement.bind_request() == request.turn_id  # catalog call
        interloper = c.accept_turn(ConversationRole.USER, "hmm")
        settlement.observe(interloper)
        tools = MemoryAgentTools(learning.service, c, request_binding=settlement)
        with pytest.raises(ExplicitMemoryAuthorizationError, match="Another utterance"):
            tools._change_turn(ExplicitMemoryAction.CORRECT)
        assert _claimed(learning, request)
        assert not _claimed(learning, interloper)
        settlement.observe(c.accept_turn(ConversationRole.ASSISTANT, "Please repeat."))
        settlement.agent_state("listening")
        await r.drain()
        assert await learning.count() == 0
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_consent_refused_for_the_bound_request_never_commits_via_learning(
    learning,
):
    class Refusing:
        def reserve_mutation(self, operation):
            raise PermissionError(
                "Fresh owner consent was not granted for this request"
            )

    facts = GatedFacts()
    r = _runtime(learning, facts)
    c = conversation()
    settlement = ReplySettlement(agent_states=True)
    settlement.agent_state("listening")
    observe = r.bind(c, learning.grant, reply_settlement=settlement)
    try:
        request = c.accept_turn(ConversationRole.USER, "I own a City")
        settlement.observe(request)
        observe(request)
        settlement.agent_state("thinking")
        tools = MemoryAgentTools(learning.service, c, request_binding=settlement)
        tools._personal_context = Refusing()
        with pytest.raises(PermissionError):
            tools._change_turn(ExplicitMemoryAction.CORRECT)
        assert _claimed(learning, request)
        settlement.observe(c.accept_turn(ConversationRole.ASSISTANT, "Not changed."))
        settlement.agent_state("listening")
        await r.drain()
        assert await learning.count() == 0
    finally:
        await r.close()


def test_without_an_interloper_the_bound_request_is_the_latest_turn(learning):
    c = conversation()
    settlement = ReplySettlement(agent_states=True)
    settlement.agent_state("listening")
    request = c.accept_turn(
        ConversationRole.USER, "Forget what you remember about my diet_preference."
    )
    settlement.observe(request)
    settlement.agent_state("thinking")
    tools = MemoryAgentTools(learning.service, c, request_binding=settlement)
    turn = tools._change_turn(ExplicitMemoryAction.FORGET)
    assert turn.turn_id == request.turn_id and _claimed(learning, request)


def test_the_binding_resets_when_the_agent_listens_again():
    c = conversation()
    settlement = ReplySettlement(agent_states=True)
    settlement.agent_state("listening")
    first = c.accept_turn(ConversationRole.USER, "one")
    settlement.observe(first)
    settlement.agent_state("thinking")
    assert settlement.bind_request() == first.turn_id
    second = c.accept_turn(ConversationRole.USER, "two")
    settlement.observe(second)
    assert settlement.bind_request() == first.turn_id  # same reply
    settlement.agent_state("listening")
    assert settlement.bind_request() == second.turn_id  # a new reply


# --- 2. ending a private wake -------------------------------------------------


class _Interruptible:
    def __init__(self, session):
        self.session = session
        self.interrupts = 0

    def interrupt(self):
        self.interrupts += 1
        future = asyncio.get_running_loop().create_future()
        future.set_result(None)
        return future


def _controller(*, released):
    session, bridge = _session_pair()
    interruptible = _Interruptible(session)
    session.interrupt = interruptible.interrupt
    config = replace(JarvisConfig(), speaker_evidence_enforcement=True)
    runtime = CanonicalActiveSpeakerRuntimeController(
        config,
        _FakeAudio(),
        session_factory=lambda _: (session, bridge),
        speaker_shadow_observer=SimpleNamespace(
            score=lambda samples, sample_rate: None
        ),
    )
    runtime._session_factory(config)
    _mark_session_ready(session)
    bridge.conversation.start()
    runtime._active_end = asyncio.Event()
    runtime._project_turns = SimpleNamespace(private_released=released)
    return runtime, bridge, interruptible


def _accept(runtime, bridge, text, *, score=None, reason="scored", resolve=True):
    turn = bridge.conversation.accept_turn(ConversationRole.USER, text)
    bridge._notify_accepted_turn(turn)
    if resolve:
        runtime._speaker_evidence.resolve(turn.turn_id, score=score, reason=reason)
    return turn


async def _settle_guard():
    for _ in range(40):
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "score", "reason", "resolve"),
    [
        ("non_owner", 0.30, "scored", True),
        ("unknown", None, "speaker_segment_too_short", True),
        ("timeout", None, "never", False),
    ],
)
async def test_an_unverified_request_after_private_context_ends_the_wake(
    label, score, reason, resolve
):
    runtime, bridge, interruptible = _controller(released=True)
    runtime._speaker_evidence._wait_seconds = 0.2
    _accept(
        runtime,
        bridge,
        "Which hotel did we book?",
        score=score,
        reason=reason,
        resolve=resolve,
    )
    await _settle_guard()
    assert runtime._active_end.is_set(), label
    assert interruptible.interrupts == 1  # speech in flight stopped
    assert runtime.private_wakes_ended == 1


@pytest.mark.asyncio
async def test_a_verified_owner_request_keeps_the_private_wake():
    runtime, bridge, interruptible = _controller(released=True)
    _accept(runtime, bridge, "Which hotel did we book?", score=0.72)
    await _settle_guard()
    assert not runtime._active_end.is_set()
    assert interruptible.interrupts == 0


@pytest.mark.asyncio
async def test_a_barge_in_by_someone_else_during_a_private_answer_ends_the_wake():
    runtime, bridge, interruptible = _controller(released=True)
    _accept(runtime, bridge, "Which hotel did we book?", score=0.72)
    await _settle_guard()
    # Jarvis is answering; someone else talks over it.
    _accept(runtime, bridge, "Tell me too!", score=0.25)
    await _settle_guard()
    assert runtime._active_end.is_set()
    assert interruptible.interrupts == 1


@pytest.mark.asyncio
async def test_a_wake_with_nothing_private_is_left_alone():
    runtime, bridge, interruptible = _controller(released=False)
    _accept(runtime, bridge, "What's the capital of Nepal?", score=0.25)
    await _settle_guard()
    assert not runtime._active_end.is_set()
    assert interruptible.interrupts == 0


def test_each_kind_of_private_release_counts():
    from jarvis.memory.memory_receipts import MemoryReceipts

    runtime = SimpleNamespace(
        _project_turns=None, _personal_context=None, _memory_receipts=MemoryReceipts()
    )
    released = CanonicalActiveSpeakerRuntimeController._private_context_released
    assert not released(runtime, "s")
    runtime._personal_context = SimpleNamespace(protected=True)
    assert released(runtime, "s")
    runtime._personal_context = None
    runtime._memory_receipts.mark_disclosed("s")
    assert released(runtime, "s")
    runtime._memory_receipts.drop_issued("s")
    runtime._project_turns = SimpleNamespace(private_released=True)
    assert released(runtime, "s")
