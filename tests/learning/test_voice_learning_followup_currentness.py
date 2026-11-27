"""Deterministic follow-up delivery races at the LiveKit context boundary."""

import asyncio
from types import SimpleNamespace

import pytest
from livekit.agents.llm import ChatContext, ChatMessage

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_clarification import (
    ClarificationBoard,
    LearningClarification,
)
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.voice.learning_followup import NOTE_PREFIX


def owner_message(message_id, text):
    return ChatMessage(id=message_id, role="user", content=[text])


class PausingAgent:
    def __init__(self, initial_message):
        self.chat_ctx = ChatContext(items=[initial_message])
        self.injected = asyncio.Event()
        self.resume_update = asyncio.Event()

    async def update_chat_ctx(self, context):
        self.chat_ctx = context.copy()
        if not self.injected.is_set():
            self.injected.set()
            await self.resume_update.wait()


class LiveSession:
    def __init__(self, agent):
        self.current_agent = agent
        self.replies = []

    def generate_reply(self, **kwargs):
        self.replies.append(kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transition",
    ["speech", "turn", "closed", "agent_swap", "session_swap", "cancelled", "current"],
)
async def test_follow_up_checks_live_owner_turn_and_preserves_local_context(transition):
    conversation = ConversationSession()
    conversation.start()
    conversation.begin_user_activity()
    turn = conversation.accept_turn(ConversationRole.USER, "Maybe Thar for the trip?")
    note = LearningClarification(
        conversation.session_id, turn.turn_id, "plan", "trip", ("vehicle",), ("Thar",)
    )
    original = owner_message("owner:original", turn.text)
    agent = PausingAgent(original)
    session = LiveSession(agent)
    learning = SimpleNamespace(
        clarifications=ClarificationBoard(), clarification_observer=None
    )
    closers = []
    registered = []
    bridge = SimpleNamespace(
        conversation=conversation,
        register_restored_context=registered.append,
        add_close_observer=closers.append,
    )
    runtime = SimpleNamespace(
        _personal_learning=learning,
        _live_session=session,
        _user_is_speaking=False,
        _agent_state="listening",
    )
    CanonicalActiveSpeakerRuntimeController._attach_learning_follow_up(
        runtime, session, bridge
    )

    assert learning.clarifications.offer(note)
    offer = learning.clarification_observer
    follow_up = offer.__self__
    offer(note)
    (delivery,) = follow_up._tasks
    await asyncio.wait_for(agent.injected.wait(), timeout=1)
    assert agent.chat_ctx.items[1].content[0].startswith(NOTE_PREFIX)

    later_items = [original]
    if transition == "speech":
        # Speech already finished without a transcript; idle is true again.
        conversation.begin_user_activity()
    elif transition == "turn":
        later_turn = conversation.accept_turn(
            ConversationRole.USER, "Tell me the weather."
        )
        new_message = owner_message("owner:new-turn", later_turn.text)
        agent.chat_ctx.items.append(new_message)
        later_items.append(new_message)
    elif transition == "closed":
        conversation.close()
    elif transition in {"agent_swap", "session_swap"}:
        replacement_message = owner_message("owner:replacement", "New agent context.")
        replacement_agent = PausingAgent(replacement_message)
        if transition == "agent_swap":
            session.current_agent = replacement_agent
        else:
            runtime._live_session = LiveSession(replacement_agent)

    if transition == "cancelled":
        await follow_up.close()
        assert delivery.cancelled()
    else:
        agent.resume_update.set()
        await delivery

    if transition == "current":
        assert session.replies == [{"allow_interruptions": True}]
        assert [item.role for item in agent.chat_ctx.items] == [
            "user",
            "user",
            "assistant",
            "user",
        ]
        assert len(registered) == 1
        offer(note)
        await asyncio.gather(*follow_up._tasks)
        assert len(session.replies) == 1
    else:
        # Both matter: a missed generation alone can leave a request that
        # causes the next ordinary reply to ask the stale question.
        assert (session.replies, agent.chat_ctx.items) == ([], later_items)
        if transition in {"agent_swap", "session_swap"}:
            assert replacement_agent.chat_ctx.items == [replacement_message]

    for close in closers:
        close()
    await follow_up.close()
