from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from livekit.agents import ConversationItemAddedEvent, UserInputTranscribedEvent
from livekit.agents.llm import ChatMessage

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.live_context import LiveContext
from jarvis.voice.hands_goal_tools import HandsGoalAgentTools
from jarvis.voice.livekit_session import LiveKitConversationBridge


class FakeAgentSession:
    def __init__(self) -> None:
        self.handlers: dict[str, Callable[[Any], None]] = {}

    def on(self, event: str, callback: Callable[[Any], None]) -> Callable[[Any], None]:
        self.handlers[event] = callback
        return callback

    def emit(self, event: str, value: Any) -> None:
        self.handlers[event](value)


class NoopAuthority:
    def authorize(self, prepared):
        raise AssertionError("authority should not run in handoff-only tests")

    def consume(self, authorized) -> None:
        raise AssertionError("authority should not run in handoff-only tests")

    def audit_result(self, *, session_id, authorized, result) -> None:
        raise AssertionError("authority should not run in handoff-only tests")

    def close(self) -> None:
        pass


class FakeOrchestrator:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def execute_goal(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "status": "succeeded", "completed_steps": 1}


def runtime() -> CapabilityRuntime:
    return CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=NoopAuthority(),
    )


def test_vad_activity_never_advances_canonical_user_generation() -> None:
    conversation = ConversationSession(session_id="activity-vs-canonical")
    conversation.start()

    first_activity = conversation.begin_user_activity()
    phantom_activity = conversation.begin_user_activity()

    assert first_activity == 1
    assert phantom_activity == 2
    assert conversation.user_activity_epoch == 2
    assert conversation.user_utterance_generation == 0

    turn = conversation.accept_turn(ConversationRole.USER, "Jarvis, unmute.")

    assert turn.user_utterance_generation == 1
    assert conversation.user_utterance_generation == 1


def test_final_user_transcript_is_canonical_before_duplicate_conversation_item() -> None:
    livekit = FakeAgentSession()
    conversation = ConversationSession(session_id="final-transcript-canonical")
    conversation.start()
    bridge = LiveKitConversationBridge(
        livekit,  # type: ignore[arg-type]
        conversation,
        LiveContext(max_recent_turns=8),
        show_transcript=False,
    )
    conversation.begin_user_activity()

    livekit.emit(
        "user_input_transcribed",
        UserInputTranscribedEvent(
            transcript="Jarvis, unmute.",
            is_final=True,
            item_id="unmute-item",
        ),
    )

    assert [turn.text for turn in conversation.turns] == ["Jarvis, unmute."]
    assert conversation.turns[0].user_utterance_generation == 1

    livekit.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(
            item=ChatMessage(
                id="unmute-item",
                role="user",
                content=["Jarvis, unmute."],
            )
        ),
    )

    assert [turn.text for turn in conversation.turns] == ["Jarvis, unmute."]
    assert bridge.live_context.recent_turns == conversation.turns


@pytest.mark.asyncio
async def test_hands_waits_for_canonical_turn_matching_current_user_activity() -> None:
    conversation = ConversationSession(session_id="hands-current-activity")
    conversation.start()
    old = conversation.accept_turn(ConversationRole.USER, "Jarvis mute")

    # This is the next real user activity. Hands must not fall back to the old turn
    # merely because the provider tool call races ahead of final transcription.
    activity_epoch = conversation.begin_user_activity()
    assert activity_epoch > 0

    fake = FakeOrchestrator()
    tools = HandsGoalAgentTools(
        runtime(),
        conversation,
        orchestrator=fake,
        transcript_wait_seconds=0.5,
    )
    pending = asyncio.create_task(tools.execute_goal())
    await asyncio.sleep(0.05)

    assert not pending.done()
    assert fake.calls == []
    assert old.user_utterance_generation == 1

    latest = conversation.accept_turn(ConversationRole.USER, "Jarvis, unmute.")
    result = await pending

    assert result["ok"] is True
    assert result["canonical_user_turn_id"] == latest.turn_id
    assert fake.calls[0]["goal"] == "Jarvis, unmute."
