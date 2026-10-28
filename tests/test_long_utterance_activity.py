from __future__ import annotations

import asyncio
from collections import defaultdict
from types import SimpleNamespace
from typing import Any

import pytest

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.live_context import LiveContext
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.voice.livekit_session import LiveKitConversationBridge, create_voice_session


class _FakeSession:
    def __init__(self) -> None:
        self.handlers: dict[str, list] = defaultdict(list)

    def on(self, event: str, callback):
        self.handlers[event].append(callback)
        return callback

    def emit(self, event: str, value: Any) -> None:
        for callback in tuple(self.handlers[event]):
            callback(value)


class _FakeAudio:
    pass


def _session_pair() -> tuple[_FakeSession, LiveKitConversationBridge]:
    session = _FakeSession()
    conversation = ConversationSession()
    bridge = LiveKitConversationBridge(
        session,  # type: ignore[arg-type]
        conversation,
        LiveContext(max_recent_turns=8),
        show_transcript=False,
    )
    return session, bridge


def _mark_session_ready(session: _FakeSession) -> None:
    session.emit(
        "agent_state_changed",
        SimpleNamespace(old_state="initializing", new_state="listening"),
    )


def test_voice_session_uses_explicit_vad_but_keeps_provider_turn_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    fake_session = _FakeSession()

    def fake_agent_session(**kwargs: Any) -> _FakeSession:
        captured.update(kwargs)
        return fake_session

    monkeypatch.setattr(
        "jarvis.voice.livekit_session._create_realtime_model", lambda _config: object()
    )
    monkeypatch.setattr("jarvis.voice.livekit_session.AgentSession", fake_agent_session)
    local_vad = object()
    monkeypatch.setattr(
        "jarvis.voice.livekit_session.inference.VAD", lambda **kwargs: local_vad
    )

    session, _bridge = create_voice_session(JarvisConfig())

    assert session is fake_session
    assert captured["vad"] is local_vad
    turn_handling = captured["turn_handling"]
    assert turn_handling["turn_detection"] is None
    assert turn_handling["interruption"]["enabled"] is True
    assert turn_handling["preemptive_generation"]["enabled"] is False


@pytest.mark.asyncio
async def test_initial_timeout_does_not_run_during_session_startup() -> None:
    config = JarvisConfig(initial_request_timeout_seconds=0.03)
    session, bridge = _session_pair()
    runtime = CanonicalActiveSpeakerRuntimeController(
        config,
        _FakeAudio(),  # type: ignore[arg-type]
        session_factory=lambda _config: (session, bridge),  # type: ignore[return-value]
    )
    runtime._active_end = asyncio.Event()
    runtime._session_factory(config)

    # Mirrors VoiceRuntimeController arming the historical timer before
    # await session.start(). It must remain disabled during provider/VAD startup.
    runtime._arm_timeout(0.01)
    await asyncio.sleep(0.02)

    assert runtime._session_ready_for_inactivity is False
    assert runtime._active_end.is_set() is False

    _mark_session_ready(session)
    assert runtime._session_ready_for_inactivity is True
    await asyncio.sleep(config.initial_request_timeout_seconds * 1.5)

    assert runtime._active_end.is_set() is True


@pytest.mark.asyncio
async def test_speech_during_startup_prevents_first_timeout_after_ready() -> None:
    config = JarvisConfig(
        initial_request_timeout_seconds=0.03,
        max_utterance_seconds=0.01,
    )
    session, bridge = _session_pair()
    runtime = CanonicalActiveSpeakerRuntimeController(
        config,
        _FakeAudio(),  # type: ignore[arg-type]
        session_factory=lambda _config: (session, bridge),  # type: ignore[return-value]
    )
    runtime._active_end = asyncio.Event()
    runtime._session_factory(config)

    session.emit(
        "user_state_changed",
        SimpleNamespace(old_state="listening", new_state="speaking"),
    )
    _mark_session_ready(session)
    runtime._arm_timeout(config.max_utterance_seconds)
    await asyncio.sleep(config.initial_request_timeout_seconds * 1.5)

    assert runtime._user_is_speaking is True
    assert runtime._active_end.is_set() is False

    session.emit(
        "user_state_changed",
        SimpleNamespace(old_state="speaking", new_state="listening"),
    )
    await asyncio.sleep(config.initial_request_timeout_seconds * 1.5)

    assert runtime._active_end.is_set() is True


@pytest.mark.asyncio
async def test_active_speech_cancels_inactivity_instead_of_starting_utterance_kill() -> (
    None
):
    config = JarvisConfig(
        initial_request_timeout_seconds=0.03,
        follow_up_timeout_seconds=0.04,
        max_utterance_seconds=0.01,
    )
    session, bridge = _session_pair()
    runtime = CanonicalActiveSpeakerRuntimeController(
        config,
        _FakeAudio(),  # type: ignore[arg-type]
        session_factory=lambda _config: (session, bridge),  # type: ignore[return-value]
    )
    runtime._active_end = asyncio.Event()
    runtime._session_factory(config)
    _mark_session_ready(session)

    session.emit(
        "user_state_changed",
        SimpleNamespace(old_state="listening", new_state="speaking"),
    )

    # Emulate the historical base handler attempting to arm max_utterance_seconds.
    runtime._arm_timeout(config.max_utterance_seconds)
    await asyncio.sleep(config.initial_request_timeout_seconds * 1.5)

    assert runtime._user_is_speaking is True
    assert runtime._active_end.is_set() is False

    session.emit(
        "user_state_changed",
        SimpleNamespace(old_state="speaking", new_state="listening"),
    )
    await asyncio.sleep(config.initial_request_timeout_seconds * 1.5)

    assert runtime._user_is_speaking is False
    assert runtime._active_end.is_set() is True


@pytest.mark.asyncio
async def test_user_activity_guard_is_order_independent_for_speaking_handler() -> None:
    config = JarvisConfig(
        initial_request_timeout_seconds=0.03,
        max_utterance_seconds=0.01,
    )
    session, bridge = _session_pair()
    runtime = CanonicalActiveSpeakerRuntimeController(
        config,
        _FakeAudio(),  # type: ignore[arg-type]
        session_factory=lambda _config: (session, bridge),  # type: ignore[return-value]
    )
    runtime._active_end = asyncio.Event()
    runtime._session_factory(config)
    _mark_session_ready(session)

    # Register a second listener after the production activity listener, mirroring
    # VoiceRuntimeController's later registration inside _run_one_session().
    def historical_base_handler(event: Any) -> None:
        if event.new_state == "speaking":
            runtime._arm_timeout(config.max_utterance_seconds)

    session.on("user_state_changed", historical_base_handler)
    session.emit(
        "user_state_changed",
        SimpleNamespace(old_state="listening", new_state="speaking"),
    )
    await asyncio.sleep(config.max_utterance_seconds * 2.0)

    assert runtime._active_end.is_set() is False


@pytest.mark.asyncio
async def test_inactivity_waits_until_agent_finishes_before_followup_window(
    monkeypatch,
):
    config = JarvisConfig(
        initial_request_timeout_seconds=0.02, follow_up_timeout_seconds=0.06
    )
    session, bridge = _session_pair()
    runtime = CanonicalActiveSpeakerRuntimeController(
        config, _FakeAudio(), session_factory=lambda _: (session, bridge)
    )
    runtime._active_end = asyncio.Event()
    runtime._session_factory(config)
    bridge.conversation.start()
    bridge.conversation.accept_turn(ConversationRole.USER, "Tell me about my bikes")
    scheduled = []

    def schedule(delay, callback):
        handle = SimpleNamespace(delay=delay, callback=callback, cancelled=False)
        handle.cancel = lambda: setattr(handle, "cancelled", True)
        scheduled.append(handle)
        return handle

    # Control only the inactivity timer, avoiding real sleeps that overshoot on a
    # busy GPU/audio workstation. No event-loop yield occurs while patched.
    with monkeypatch.context() as patch:
        patch.setattr(asyncio.get_running_loop(), "call_later", schedule)
        _mark_session_ready(session)
        previous = scheduled[-1]
        for old, new in [("listening", "thinking"), ("thinking", "speaking")]:
            session.emit(
                "agent_state_changed", SimpleNamespace(old_state=old, new_state=new)
            )
            runtime._arm_timeout(0.01)
            assert runtime._timeout_handle is None
            previous.callback()  # even an already queued old expiry is harmless
            assert not runtime._active_end.is_set()
        session.emit(
            "agent_state_changed",
            SimpleNamespace(old_state="speaking", new_state="listening"),
        )
        assert previous.cancelled
        assert scheduled[-1].delay == config.follow_up_timeout_seconds
        assert not runtime._active_end.is_set()
        scheduled[-1].callback()
        assert runtime._active_end.is_set()
        runtime._cancel_timeout()


@pytest.mark.asyncio
async def test_explicit_standby_keeps_its_bounded_deadline_while_agent_speaks():
    config = JarvisConfig(initial_request_timeout_seconds=1)
    session, bridge = _session_pair()
    runtime = CanonicalActiveSpeakerRuntimeController(
        config, _FakeAudio(), session_factory=lambda _: (session, bridge)
    )
    runtime._active_end = asyncio.Event()
    runtime._session_factory(config)
    _mark_session_ready(session)
    runtime._standby_requested = True
    runtime._arm_timeout(0.02)
    session.emit(
        "agent_state_changed",
        SimpleNamespace(old_state="listening", new_state="speaking"),
    )
    session.emit(
        "user_state_changed",
        SimpleNamespace(old_state="listening", new_state="speaking"),
    )
    await asyncio.sleep(0.04)
    assert runtime._active_end.is_set()
    runtime._cancel_timeout()
