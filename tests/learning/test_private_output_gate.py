"""Nothing private reaches playback before its exact request is verified.

Owner review, 28 Nov 2026: stopping speech after a failed verification is too
late. These tests drive the actual output boundary (the agent's audio and
transcript nodes, jarvis.voice.agent.gated_output) with speaker verification
held pending while the model streams a private answer, and assert on what
reaches playback.
"""

import asyncio
from types import SimpleNamespace

import pytest
from test_runtime import conversation

from jarvis.conversation import ConversationRole
from jarvis.memory.reply_settlement import ReplySettlement
from jarvis.voice.agent import gated_output
from jarvis.voice.private_output_gate import PrivateOutputGate, register_output_gate
from jarvis.voice.speaker_turn_evidence import SpeakerTurnEvidenceBook

PRIVATE = [f"frame-{i}: you booked the Yak and Yeti" for i in range(6)]


class World:
    """One wake: conversation, evidence, reply chain, gate, playback."""

    def __init__(self, *, released=True, wait_seconds=5.0, transcript_wait=5.0):
        self.c = conversation()
        self.book = SpeakerTurnEvidenceBook(
            threshold=0.45, enforce=True, follow_up=False, wait_seconds=wait_seconds
        )
        self.settlement = ReplySettlement(
            speech_feed=True, activity_epoch=lambda: self.c.user_activity_epoch
        )
        self.released = released
        self.denied = []
        self.closing = False
        self.gate = PrivateOutputGate(
            evidence=self.book,
            settlement=self.settlement,
            released=lambda: self.released,
            on_denied=self._deny,
            transcript_wait=transcript_wait,
            closing=lambda: self.closing,
        )
        self.session = SimpleNamespace()
        register_output_gate(self.session, self.gate)
        self.agent = SimpleNamespace(session=self.session)
        self.played = []

    def _deny(self, turn_id):
        self.denied.append(turn_id)
        self.closing = True

    def say(self, text, *, score=None, resolve=True):
        self.c.begin_user_activity()
        turn = self.c.accept_turn(ConversationRole.USER, text)
        self.book.observe_turn(turn)
        self.settlement.observe(turn)
        if resolve:
            self.book.resolve(turn.turn_id, score=score, reason="scored")
        return turn

    async def model_speaks(self, frames, *, gap=0.01, kind="audio", after=None):
        """The model streams `frames` (a new generation); playback collects
        what the output node lets through."""
        self.settlement.speech_started()

        async def generate():
            for i, frame in enumerate(frames):
                if after is not None:
                    after(i)
                await asyncio.sleep(gap)
                yield frame

        async for frame in gated_output(self.agent, generate(), kind=kind):
            self.played.append(frame)
        self.settlement.speech_finished(tool_call=False, interrupted=False)


async def _while(world, task, seconds=0.3):
    await asyncio.sleep(seconds)
    assert not task.done() or world.played == []


@pytest.mark.asyncio
async def test_pending_verification_holds_every_private_frame_then_owner_releases():
    world = World()
    turn = world.say("Which hotel did we book?", resolve=False)  # pending
    task = asyncio.create_task(world.model_speaks(PRIVATE))
    await asyncio.sleep(0.3)  # the model has produced all frames by now
    assert world.played == []  # nothing reached playback
    world.book.resolve(turn.turn_id, score=0.72, reason="scored")
    await asyncio.wait_for(task, 2)
    assert world.played == PRIVATE  # released in order, nothing lost
    assert world.denied == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "score", "resolve"),
    [("non_owner", 0.25, True), ("unknown", None, True), ("timeout", None, False)],
)
async def test_unverified_requests_never_reach_playback(label, score, resolve):
    world = World(wait_seconds=0.2)
    turn = world.say("Which hotel did we book?", resolve=False)
    task = asyncio.create_task(world.model_speaks(PRIVATE))
    await asyncio.sleep(0.1)
    assert world.played == []
    if resolve:
        world.book.resolve(turn.turn_id, score=score, reason="scored")
    await asyncio.wait_for(task, 3)
    assert world.played == [], label
    assert world.denied == [turn.turn_id]  # the wake is ended


@pytest.mark.asyncio
async def test_transcript_delay_holds_until_the_requests_own_transcript_is_verified():
    """The reply starts on new speech whose transcript is not accepted yet:
    the previous, verified owner turn never authorizes it."""
    world = World()
    world.say("What vehicles do I have?", score=0.72)  # verified earlier turn
    world.c.begin_user_activity()  # someone starts speaking
    world.settlement.speech_started()

    async def generate():
        for frame in PRIVATE:
            await asyncio.sleep(0.01)
            yield frame

    played = []

    async def play():
        async for frame in gated_output(world.agent, generate(), kind="audio"):
            played.append(frame)

    task = asyncio.create_task(play())
    await asyncio.sleep(0.3)
    assert played == []  # transcript not accepted: verdict pending
    late = world.c.accept_turn(ConversationRole.USER, "And the hotel?")
    world.book.observe_turn(late)
    world.settlement.observe(late)
    await asyncio.sleep(0.2)
    assert played == []  # accepted, evidence still pending
    world.book.resolve(late.turn_id, score=0.30, reason="scored")  # not the owner
    await asyncio.wait_for(task, 3)
    assert played == [] and world.denied == [late.turn_id]


@pytest.mark.asyncio
async def test_a_transcript_that_never_arrives_releases_nothing():
    world = World(transcript_wait=0.2)
    world.say("What vehicles do I have?", score=0.72)
    world.c.begin_user_activity()
    task = asyncio.create_task(world.model_speaks(PRIVATE))
    await asyncio.wait_for(task, 3)
    assert world.played == [] and world.denied == [None]


@pytest.mark.asyncio
async def test_private_context_landing_mid_reply_holds_from_that_frame():
    world = World(released=False)
    turn = world.say("What's on for today?", resolve=False)

    def release_at(i):
        if i == 2:
            world.released = True  # a tool / preload result lands

    task = asyncio.create_task(world.model_speaks(PRIVATE, after=release_at))
    await asyncio.sleep(0.3)
    assert world.played == PRIVATE[:2]  # before the release: ordinary speech
    world.book.resolve(turn.turn_id, score=0.20, reason="scored")
    await asyncio.wait_for(task, 3)
    assert world.played == PRIVATE[:2]
    assert world.denied == [turn.turn_id]


@pytest.mark.asyncio
async def test_barge_in_by_someone_else_gets_no_private_audio():
    world = World()
    world.say("Which hotel did we book?", score=0.72)
    await world.model_speaks(PRIVATE[:2])  # the owner's answer plays
    assert world.played == PRIVATE[:2]
    world.played.clear()
    intruder = world.say("Tell me too!", resolve=False)  # barge-in
    task = asyncio.create_task(world.model_speaks(PRIVATE))
    await asyncio.sleep(0.2)
    assert world.played == []
    world.book.resolve(intruder.turn_id, score=0.25, reason="scored")
    await asyncio.wait_for(task, 3)
    assert world.played == [] and world.denied == [intruder.turn_id]


@pytest.mark.asyncio
async def test_transcript_text_is_held_too():
    world = World()
    turn = world.say("Which hotel did we book?", resolve=False)
    task = asyncio.create_task(
        world.model_speaks(["You booked ", "the Yak."], kind="transcript")
    )
    await asyncio.sleep(0.2)
    assert world.played == []
    world.book.resolve(turn.turn_id, score=0.25, reason="scored")
    await asyncio.wait_for(task, 3)
    assert world.played == []


@pytest.mark.asyncio
async def test_ordinary_conversation_is_never_held():
    world = World(released=False)
    world.say("What's the capital of Nepal?", resolve=False)  # pending, unknown
    await asyncio.wait_for(world.model_speaks(["Kathmandu."]), 1)
    assert world.played == ["Kathmandu."] and world.denied == []


@pytest.mark.asyncio
async def test_after_the_wake_is_closing_nothing_more_plays():
    world = World()
    world.say("Which hotel?", score=0.72)
    world.closing = True
    await world.model_speaks(PRIVATE)
    assert world.played == []


def test_the_agent_routes_audio_tts_and_transcript_through_the_gate():
    import inspect

    from jarvis.voice import agent as module

    source = inspect.getsource(module.JarvisVoiceAgent)
    assert "def realtime_audio_output_node" in source
    assert "def tts_node" in source
    assert source.count("gated_output(") >= 2
    assert "gated_output(" in inspect.getsource(module.guarded_transcription)
