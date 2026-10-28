import asyncio
from time import monotonic

import pytest
from test_voice_runtime import FakeAudio, FakeSession

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationSession
from jarvis.memory.live_context import LiveContext
from jarvis.voice.livekit_session import LiveKitConversationBridge
from jarvis.voice.runtime import VoiceRuntimeController


@pytest.mark.asyncio
async def test_private_response_rollover_listens_without_wake_and_expires_on_silence():
    sessions = [FakeSession(), FakeSession()]
    bridges = [
        LiveKitConversationBridge(
            s,
            ConversationSession(),
            LiveContext(max_recent_turns=8),
            show_transcript=False,
        )
        for s in sessions
    ]
    remaining = list(zip(sessions, bridges, strict=True))

    class FollowupAudio(FakeAudio):
        def activate_session(
            self,
            incoming,
            *,
            pre_roll_after_monotonic=None,
            retain_since_boundary=False,
        ):
            self.retained_transition = retain_since_boundary
            super().activate_session(
                incoming, pre_roll_after_monotonic=pre_roll_after_monotonic
            )

    audio = FollowupAudio()
    runtime = VoiceRuntimeController(
        JarvisConfig(
            initial_request_timeout_seconds=0.01, follow_up_timeout_seconds=0.12
        ),
        audio,
        session_factory=lambda _: remaining.pop(0),
    )
    task = asyncio.create_task(runtime._run_one_session())
    try:
        await asyncio.wait_for(sessions[0].started.wait(), 1)
        marker = monotonic()
        runtime._follow_up_requested_after = marker
        runtime._active_end.set()
        await asyncio.wait_for(sessions[1].started.wait(), 1)
        assert sessions[0].closed
        assert not bridges[1].conversation.turns
        assert audio.pre_roll_after_monotonic == marker
        assert audio.retained_transition
        await asyncio.sleep(0.04)
        assert not task.done()
        assert sessions[1].generated_replies == []
        await asyncio.wait_for(task, 1)
        assert sessions[1].closed
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["standby", "shutdown", "provider_error"])
async def test_followup_request_does_not_override_terminal_session_end(stop):
    from livekit.agents import CloseEvent, CloseReason

    class Audio(FakeAudio):
        def activate_session(self, incoming, *, retain_since_boundary=False, **kwargs):
            super().activate_session(incoming, **kwargs)

    sessions = [FakeSession(), FakeSession()]
    bridges = [
        LiveKitConversationBridge(
            s,
            ConversationSession(),
            LiveContext(max_recent_turns=8),
            show_transcript=False,
        )
        for s in sessions
    ]
    remaining = list(zip(sessions, bridges, strict=True))
    runtime = VoiceRuntimeController(
        JarvisConfig(
            initial_request_timeout_seconds=0.05, follow_up_timeout_seconds=0.05
        ),
        Audio(),
        session_factory=lambda _: remaining.pop(0),
    )
    task = asyncio.create_task(runtime._run_one_session())
    try:
        await asyncio.wait_for(sessions[0].started.wait(), 1)
        runtime._follow_up_requested_after = monotonic()
        if stop == "standby":
            runtime._standby_requested = True
        elif stop == "shutdown":
            runtime._shutdown.set()
        else:
            sessions[0].emit("close", CloseEvent(reason=CloseReason.ERROR))
        runtime._active_end.set()
        await asyncio.wait_for(task, 1)
        assert len(remaining) == 1
        assert not sessions[1].started.is_set()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
