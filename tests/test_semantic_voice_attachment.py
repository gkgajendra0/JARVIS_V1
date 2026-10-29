"""Native accepted-turn semantic attachment is strictly opt-in and revocable."""

from __future__ import annotations

import asyncio

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.conversation_semantics import SemanticAction, SemanticProposal
from jarvis.voice.semantic_context_bridge import attach_semantic_voice_context


class BridgeFixture:
    def __init__(self):
        self.conversation = ConversationSession()
        self.conversation.start()
        self.accepted = []
        self.closers = []

    def add_accepted_turn_observer(self, callback):
        self.accepted.append(callback)

    def add_close_observer(self, callback):
        self.closers.append(callback)

    def user(self, text):
        turn = self.conversation.accept_turn(ConversationRole.USER, text)
        for callback in self.accepted:
            callback(turn)
        return turn

    def close(self):
        self.conversation.close()
        for callback in self.closers:
            callback()


@pytest.mark.asyncio
@pytest.mark.parametrize("deadline, succeeds", [(0.02, False), (0.2, True)])
async def test_explicit_extraction_deadline_allows_slow_async_result_without_blocking_voice(
    deadline, succeeds
):
    bridge = BridgeFixture()
    release = asyncio.Event()

    async def slow(turn):
        await release.wait()
        return [topic(turn)]

    attachment = attach_semantic_voice_context(
        bridge,
        producer=slow,
        authorization_binding=lambda: "grant",
        timeout_seconds=deadline,
    )
    try:
        bridge.user("Nepal trip")
        assert attachment.state.snapshot() is None
        await asyncio.sleep(0.06)
        release.set()
        await attachment.pipeline.drain()
        assert attachment.state.active_topic == ("Nepal trip" if succeeds else None)
        assert attachment.pipeline.status.failures == (0 if succeeds else 1)
    finally:
        bridge.close()
        await attachment.wait_closed()


def topic(turn):
    return SemanticProposal(
        action=SemanticAction.TOPIC,
        quote=turn.text,
        start=0,
        end=len(turn.text),
        value=turn.text,
    )


@pytest.mark.asyncio
async def test_canonical_turn_attachment_tracks_state_without_blocking_callback():
    bridge = BridgeFixture()

    async def producer(turn):
        return [topic(turn)]

    attachment = attach_semantic_voice_context(
        bridge, producer=producer, authorization_binding=lambda: "grant-generation-1"
    )
    assert attachment.state.active_topic is None
    bridge.user("Nepal trip")
    await attachment.pipeline.drain()
    assert attachment.state.active_topic == "Nepal trip"
    assert attachment.pipeline.status.applied == 1
    bridge.close()
    assert attachment.state.snapshot() is None
    await attachment.wait_closed()


@pytest.mark.asyncio
async def test_close_discards_inflight_semantic_inference():
    bridge = BridgeFixture()
    started = asyncio.Event()
    proceed = asyncio.Event()

    async def producer(turn):
        started.set()
        await proceed.wait()
        return [topic(turn)]

    attachment = attach_semantic_voice_context(
        bridge, producer=producer, authorization_binding=lambda: "grant-generation-1"
    )
    bridge.user("Nepal trip")
    await asyncio.wait_for(started.wait(), timeout=2)
    bridge.close()
    proceed.set()
    await asyncio.wait_for(attachment.wait_closed(), timeout=3)
    assert attachment.state.snapshot() is None


@pytest.mark.asyncio
async def test_no_binding_never_creates_context():
    bridge = BridgeFixture()
    calls = []

    async def producer(turn):
        calls.append(turn)
        return [topic(turn)]

    attachment = attach_semantic_voice_context(
        bridge, producer=producer, authorization_binding=lambda: None
    )
    bridge.user("Nepal trip")
    await attachment.pipeline.drain()
    assert attachment.state.snapshot() is None
    assert calls == []
    bridge.close()
    await attachment.wait_closed()


@pytest.mark.asyncio
async def test_assistant_turn_is_not_a_user_context_source():
    bridge = BridgeFixture()

    async def producer(turn):
        return [topic(turn)]

    attachment = attach_semantic_voice_context(
        bridge, producer=producer, authorization_binding=lambda: "owner-session"
    )
    turn = bridge.conversation.accept_turn(
        ConversationRole.ASSISTANT, "You are driving a Jimny"
    )
    for callback in bridge.accepted:
        callback(turn)
    await attachment.pipeline.drain()
    assert attachment.state.snapshot() is None
    bridge.close()
    await attachment.wait_closed()


def test_attachment_requires_explicit_trusted_inputs():
    bridge = BridgeFixture()
    with pytest.raises(TypeError, match="mandatory"):
        attach_semantic_voice_context(
            bridge, producer=None, authorization_binding=lambda: "owner"
        )


def test_per_voice_session_writer_factory_never_reuses_canonical_conversation():
    from jarvis.voice.semantic_context_bridge import (
        resolve_session_commit_callback,
    )

    conversations = []
    writers = []

    def writer_factory(conversation):
        conversations.append(conversation)

        async def record(turn, proposals, before, after, source_plan_epoch):
            assert conversation is not None

        writers.append(record)
        return record

    first = BridgeFixture()
    second = BridgeFixture()
    writer_one = resolve_session_commit_callback(
        first.conversation, direct=None, factory=writer_factory
    )
    writer_two = resolve_session_commit_callback(
        second.conversation, direct=None, factory=writer_factory
    )
    assert writer_one is writers[0]
    assert writer_two is writers[1]
    assert writer_one is not writer_two
    assert conversations == [first.conversation, second.conversation]


def test_invalid_or_ambiguous_commit_callback_factory_is_rejected():
    from jarvis.voice.semantic_context_bridge import (
        resolve_session_commit_callback,
    )

    bridge = BridgeFixture()

    async def recorder(*args):
        pass

    with pytest.raises(ValueError, match="cannot both"):
        resolve_session_commit_callback(
            bridge.conversation, direct=recorder, factory=lambda _c: recorder
        )
    with pytest.raises(TypeError, match="returned no callback"):
        resolve_session_commit_callback(
            bridge.conversation, direct=None, factory=lambda _c: None
        )
    with pytest.raises(TypeError, match="returned no callback"):
        resolve_session_commit_callback(
            bridge.conversation, direct=None, factory=lambda _c: "not-a-function"
        )
    assert (
        resolve_session_commit_callback(bridge.conversation, direct=None, factory=None)
        is None
    )


@pytest.mark.asyncio
async def test_shutdown_remains_bounded_if_model_ignores_first_cancellation():
    bridge = BridgeFixture()
    started = asyncio.Event()
    finally_release = asyncio.Event()

    async def stubborn_producer(turn):
        started.set()
        try:
            await finally_release.wait()
        except asyncio.CancelledError:
            # A third-party network client may swallow one cancellation.
            await finally_release.wait()
        return [topic(turn)]

    attachment = attach_semantic_voice_context(
        bridge,
        producer=stubborn_producer,
        authorization_binding=lambda: "trusted-owner-session",
    )
    bridge.user("Nepal trip")
    await asyncio.wait_for(started.wait(), timeout=2)
    bridge.close()
    try:
        await asyncio.wait_for(attachment.wait_closed(), timeout=3)
        assert attachment.state.snapshot() is None
    finally:
        # Release the stubborn task too: never leave it behind in pytest.
        finally_release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    assert attachment.state.snapshot() is None
