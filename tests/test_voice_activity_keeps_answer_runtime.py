"""Production controller: VAD "speaking" with no transcript keeps the voice
session and its pending personal answer (speaker-eval-2, 2026-11-19); a
genuine new turn and a deliberate barge-in still end it; memory writes stay
strict."""

import asyncio
from types import SimpleNamespace

import pytest
import test_personal_context_runtime as context_fixtures
from test_long_utterance_activity import _session_pair
from test_personal_context_runtime import Sink
from test_production_hands_voice_wiring import _runtime

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationRole
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
    personal_speech_finished,
)
from jarvis.voice.memory_tools import MemoryAgentTools

personal = context_fixtures.personal


async def controller(personal, question):
    prototype, service, _, authority, _ = personal
    config = JarvisConfig(personal_context_mode="apply")
    session, bridge = _session_pair()
    capabilities = _runtime()
    for name in (
        "authorize_personal_context",
        "consume_personal_context",
        "validate_personal_context",
        "invalidate_personal_context",
    ):
        setattr(capabilities, name, getattr(authority, name))
    runtime = CanonicalActiveSpeakerRuntimeController(
        config,
        SimpleNamespace(output=Sink()),
        session_factory=lambda _: (session, bridge),
        memory_runtime=SimpleNamespace(service=service, retrieval=prototype._retrieval),
        capability_runtime=capabilities,
    )
    runtime._active_end = asyncio.Event()
    runtime._session_factory(config)
    bridge.conversation.start()
    session.emit(
        "agent_state_changed",
        SimpleNamespace(old_state="initializing", new_state="listening"),
    )
    bridge._accept_canonical_turn(ConversationRole.USER, question)
    context = runtime._personal_context
    catalog = await context.catalog()
    assert (await context.read(catalog["catalog_id"], [0]))["status"] == "selected"
    return runtime, session, bridge, context


def vad(session, state_from, state_to):
    session.emit(
        "user_state_changed",
        SimpleNamespace(old_state=state_from, new_state=state_to),
    )


def speech(interrupted):
    return SimpleNamespace(interrupted=interrupted, chat_items=[])


@pytest.mark.asyncio
async def test_q2_vad_burst_keeps_the_session_and_the_answer_plays(personal):
    runtime, session, _, context = await controller(
        personal, "Which one is better for Spiti trip?"
    )
    try:
        vad(session, "listening", "speaking")  # 90 ms, no transcript
        vad(session, "speaking", "listening")
        assert not runtime._active_end.is_set()
        assert await context.allow_audio()
        context.playback_finished()
        personal_speech_finished(context, None, speech(False), provider="gemini")
        assert runtime._active_end.is_set()
        assert context.retirement_reason == "response_completed"
        assert runtime._follow_up_requested_after is not None
    finally:
        runtime._cancel_timeout()


@pytest.mark.asyncio
async def test_a_genuine_new_turn_after_activity_ends_the_old_answer(personal):
    runtime, session, bridge, context = await controller(
        personal, "What should I pack?"
    )
    try:
        vad(session, "listening", "speaking")
        assert not runtime._active_end.is_set()
        bridge._accept_canonical_turn(ConversationRole.USER, "Actually, Ladakh.")
        assert runtime._active_end.is_set()
        assert context.retirement_reason == "user_activity"
        assert not await context.allow_audio()
    finally:
        runtime._cancel_timeout()


@pytest.mark.asyncio
async def test_deliberate_barge_in_still_stops_the_answer(personal):
    runtime, session, _, context = await controller(
        personal, "Which one is better for Spiti trip?"
    )
    try:
        assert await context.allow_audio()  # answer playing
        vad(session, "listening", "speaking")
        # The provider's barge-in interrupts the speech handle.
        personal_speech_finished(context, None, speech(True), provider="gemini")
        assert runtime._active_end.is_set()
        assert context._closed and not await context.allow_audio()
    finally:
        runtime._cancel_timeout()


@pytest.mark.asyncio
async def test_memory_write_is_still_voided_by_voice_activity(personal):
    session, service, conversation, authority, _ = personal
    conversation.accept_turn(ConversationRole.USER, "Remember my home city is Sagar")
    tools = MemoryAgentTools(service, conversation, personal_context=session)
    authority.wait.clear()
    task = asyncio.create_task(tools.remember(predicate="home city", value="Sagar"))
    await asyncio.to_thread(authority.entered.wait, 1)
    conversation.begin_user_activity()
    session.observe_activity()
    authority.wait.set()
    with pytest.raises(PermissionError):
        await task
    from jarvis.memory.service import MemoryNotFoundError

    with pytest.raises(MemoryNotFoundError):
        await service.inspect_exact(predicate="home city")
