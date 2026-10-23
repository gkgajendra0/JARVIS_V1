from livekit.agents import ConversationItemAddedEvent, UserInputTranscribedEvent
from livekit.agents.llm import ChatMessage
from tests.gemini_fallback.live_helpers import SessionEvents

from jarvis.conversation import ConversationSession, ConversationStatus
from jarvis.memory.live_context import LiveContext
from jarvis.voice.livekit_session import LiveKitConversationBridge


def bridge():
    session = SessionEvents()
    conversation = ConversationSession()
    conversation.start()
    canonical = LiveKitConversationBridge(
        session, conversation, LiveContext(max_recent_turns=8), show_transcript=False
    )
    return session, canonical


def test_projection_restores_accepted_turns_without_notifying_learning():
    session, canonical = bridge()
    observed = []
    canonical.add_accepted_turn_observer(observed.append)
    session.emit(
        "user_input_transcribed",
        UserInputTranscribedEvent(
            transcript="मेरे पास City है", is_final=True, item_id="source-1"
        ),
    )
    session.emit(
        "conversation_item_added",
        ConversationItemAddedEvent(
            item=ChatMessage(id="reply-1", role="assistant", content=["ठीक है"])
        ),
    )
    original = canonical.conversation.turns
    context = canonical.project_accepted_context()
    assert [m.text_content for m in context.messages()] == ["मेरे पास City है", "ठीक है"]
    assert len(observed) == 2
    assert canonical.conversation.turns == original
    epoch = canonical.begin_transport_handoff()
    for item in context.items:
        session.emit("conversation_item_added", ConversationItemAddedEvent(item=item))
    canonical.finish_transport_handoff(epoch)
    for item in context.items:
        session.emit("conversation_item_added", ConversationItemAddedEvent(item=item))
    assert len(observed) == 2
    assert canonical.conversation.status is ConversationStatus.ACTIVE


def test_transition_drops_unaccepted_transcript_and_does_not_close_logical_context():
    session, canonical = bridge()
    epoch = canonical.begin_transport_handoff()
    session.emit(
        "user_input_transcribed",
        UserInputTranscribedEvent(
            transcript="unaccepted transition audio", is_final=True
        ),
    )
    assert canonical.conversation.turns == ()
    canonical.finish_transport_handoff(epoch)
    assert canonical.conversation.status is ConversationStatus.ACTIVE


import pytest
from tests.learning.conftest import authority, authority_parts, clock, learning

__all__ = ["authority", "authority_parts", "clock", "learning"]


@pytest.mark.asyncio
async def test_private_restore_checks_existing_grant_without_hello_or_audio_side_effects(
    learning, clock, authority_parts
):
    from tests.learning.context_query_helpers import context_session, seed_item

    await seed_item(learning)
    async with context_session(learning) as (personal, _, retired):
        catalog = await personal.catalog()
        result = await personal.read(catalog["catalog_id"], [0])
        assert result["status"] == "selected"
        assert await personal.validate_transport_restore()
        assert not personal._audio_started
        clock.advance(301)
        assert not await personal.validate_transport_restore()
        assert retired
        assert len(authority_parts.hello.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["lock", "forget"])
async def test_late_provider_audio_and_context_restore_remain_blocked_after_revocation(
    learning, authority_parts, revocation
):
    from dataclasses import replace

    from livekit import rtc
    from livekit.agents import llm
    from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities
    from tests.gemini_fallback.live_helpers import ProviderModel
    from tests.learning.context_query_helpers import context_session, seed_item

    from jarvis.memory.types import AuthorityClass, MemorySourceClass
    from jarvis.voice.gemini_transport import (
        GeminiEpochAudioOutput,
        GeminiTransportState,
        GuardedGeminiRealtimeModel,
    )
    from jarvis.voice.personal_context_audio import PersonalContextAudioOutput

    class PhysicalSink(AudioOutput):
        def __init__(self):
            super().__init__(
                label="fictional-speaker",
                sample_rate=16000,
                capabilities=AudioOutputCapabilities(pause=False),
            )
            self.frames = []

        async def capture_frame(self, frame):
            self.frames.append(frame)

        def clear_buffer(self):
            pass

        def flush(self):
            pass

    selected = await seed_item(learning)
    async with context_session(learning) as (personal, _, retired):
        catalog = await personal.catalog()
        assert (await personal.read(catalog["catalog_id"], [0]))["status"] == "selected"
        state = GeminiTransportState(
            epoch=1,
            current_epoch=lambda: 1,
            authorize=personal.validate_transport_restore,
        )
        model = GuardedGeminiRealtimeModel(ProviderModel(), state)
        transport = model.session()
        physical = PhysicalSink()
        epoch_output = GeminiEpochAudioOutput(physical, lambda: 1)
        output = PersonalContextAudioOutput(epoch_output, personal)
        try:
            before = llm.ChatContext.empty()
            await transport.update_chat_ctx(before)
            if revocation == "lock":
                authority_parts.windows.lock_unlock()
            else:
                source = replace(
                    learning.plan.mutations[0].source,
                    source_id="fictional-forget",
                    source_class=MemorySourceClass.OWNER_EXPLICIT,
                    authority_class=AuthorityClass.OWNER_EXPLICIT,
                )
                await learning.service.forget_exact(
                    predicate=selected.predicate, source=source
                )
            frame = rtc.AudioFrame.create(16000, 1, 160)
            frame.userdata["jarvis_transport_epoch"] = 1
            await output.capture_frame(frame)
            assert physical.frames == [] and retired
            with pytest.raises(llm.RealtimeError):
                await transport.update_chat_ctx(llm.ChatContext.empty())
        finally:
            output.detach()
            epoch_output.detach()
            await transport.aclose()
            await model.aclose()
