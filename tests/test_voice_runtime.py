from __future__ import annotations

import asyncio
from collections import defaultdict
from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import CloseEvent, CloseReason, ConversationItemAddedEvent
from livekit.agents.llm import ChatMessage

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationSession, ConversationStatus
from jarvis.voice.audio import LocalAudioOutput
from jarvis.voice.livekit_session import LiveKitConversationBridge
from jarvis.voice.runtime import (
    VoiceRuntimeController,
    VoiceRuntimeState,
    _is_exit_intent,
)


class FakeSession:
    def __init__(self, *, start_error: Exception | None = None) -> None:
        self.handlers: dict[str, list] = defaultdict(list)
        self.input = SimpleNamespace(audio=None)
        self.output = SimpleNamespace(audio=None)
        self.started = asyncio.Event()
        self.closed = False
        self.start_error = start_error

    def on(self, event: str, callback):
        self.handlers[event].append(callback)
        return callback

    def emit(self, event: str, value: Any) -> None:
        for callback in tuple(self.handlers[event]):
            callback(value)

    async def start(self, *, agent: Any) -> None:
        del agent
        self.started.set()
        if self.start_error is not None:
            raise self.start_error

    async def aclose(self) -> None:
        self.closed = True
        self.emit("close", CloseEvent(reason=CloseReason.USER_INITIATED))


class FakeAudio:
    def __init__(self) -> None:
        self.output = LocalAudioOutput(output_device=None)
        self.activated = False
        self.deactivated = False

    def activate_session(self, session_input) -> None:
        del session_input
        self.activated = True

    def deactivate_session(self) -> None:
        self.deactivated = True


def runtime_with_session(
    *,
    initial_timeout: float = 1,
    start_error: Exception | None = None,
) -> tuple[VoiceRuntimeController, FakeSession, ConversationSession, FakeAudio]:
    session = FakeSession(start_error=start_error)
    conversation = ConversationSession()
    bridge = LiveKitConversationBridge(
        session,  # type: ignore[arg-type]
        conversation,
        show_transcript=False,
    )
    audio = FakeAudio()
    config = JarvisConfig(initial_request_timeout_seconds=initial_timeout)
    runtime = VoiceRuntimeController(
        config,
        audio,  # type: ignore[arg-type]
        session_factory=lambda _: (session, bridge),  # type: ignore[arg-type,return-value]
    )
    return runtime, session, conversation, audio


@pytest.mark.parametrize(
    "text",
    [
        "Go to sleep.",
        "Ok, Jarvis, go to sleep.",
        "Jarvis, please go to sleep now.",
        "Please end the session.",
        "ठीक है, जार्विस सो जाओ।",
    ],
)
def test_exit_intent_accepts_bounded_polite_variants(text: str) -> None:
    assert _is_exit_intent(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Do not go to sleep.",
        "Tell me why you go to sleep.",
        "What does go to sleep mean?",
        "Jarvis, continue.",
    ],
)
def test_exit_intent_rejects_negated_or_discussed_phrases(text: str) -> None:
    assert _is_exit_intent(text) is False


@pytest.mark.asyncio
async def test_explicit_exit_ends_active_session_and_cleans_up() -> None:
    runtime, session, conversation, audio = runtime_with_session()
    task = asyncio.create_task(runtime._run_one_session())
    await session.started.wait()
    assert runtime.state is VoiceRuntimeState.ACTIVE

    session.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(
            item=ChatMessage(id="exit", role="user", content=["Jarvis, go to sleep."])
        ),
    )
    await asyncio.wait_for(task, timeout=1)

    assert audio.activated is True
    assert audio.deactivated is True
    assert session.closed is True
    assert conversation.status is ConversationStatus.CLOSED


@pytest.mark.asyncio
async def test_initial_timeout_ends_session_without_provider_activity() -> None:
    runtime, session, _, audio = runtime_with_session(initial_timeout=0.01)

    await asyncio.wait_for(runtime._run_one_session(), timeout=1)

    assert session.closed is True
    assert audio.deactivated is True


@pytest.mark.asyncio
async def test_provider_start_failure_marks_conversation_failed_and_cleans_up() -> None:
    runtime, session, conversation, audio = runtime_with_session(
        start_error=RuntimeError("provider unavailable")
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await runtime._run_one_session()

    assert session.closed is True
    assert audio.deactivated is True
    assert conversation.status is ConversationStatus.FAILED
