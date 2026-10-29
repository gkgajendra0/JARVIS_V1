"""Per-wake semantic factories run through the canonical voice controller."""

import asyncio
from types import SimpleNamespace

import pytest
from test_long_utterance_activity import _session_pair
from test_production_hands_voice_wiring import _runtime

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationRole
from jarvis.memory.conversation_semantics import SemanticAction, SemanticProposal
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.voice.semantic_context_bridge import SemanticSessionComponents


async def producer(turn):
    return []


@pytest.mark.asyncio
async def test_controller_constructs_distinct_semantics_on_each_wake():
    config = JarvisConfig(personal_context_mode="apply")
    seen = []

    def factory(conversation):
        seen.append(conversation)
        return SemanticSessionComponents(
            conversation=conversation,
            producer=producer,
            authorization_binding=lambda: None,
        )

    controller = CanonicalActiveSpeakerRuntimeController(
        config,
        SimpleNamespace(output=None),
        session_factory=lambda config: _session_pair(),
        memory_runtime=SimpleNamespace(retrieval=object()),
        capability_runtime=_runtime(),
        semantic_session_factory=factory,
    )
    attachments = []
    for _ in range(2):
        controller._session_factory(config)
        attachment = controller._semantic_context_attachment
        attachments.append(attachment)
        attachment.close()
        await attachment.wait_closed()
    assert len(seen) == 2
    assert seen[0] is not seen[1]
    assert attachments[0] is not attachments[1]


@pytest.mark.asyncio
async def test_cloud_lab_deadline_reaches_actual_controller_pipeline():
    config = JarvisConfig(personal_context_mode="apply")

    async def delayed(turn):
        await asyncio.sleep(5.1)
        return [
            SemanticProposal(
                action=SemanticAction.TOPIC,
                quote=turn.text,
                start=0,
                end=len(turn.text),
                value=turn.text,
            )
        ]

    controller = CanonicalActiveSpeakerRuntimeController(
        config,
        SimpleNamespace(output=None),
        session_factory=lambda config: _session_pair(),
        memory_runtime=SimpleNamespace(retrieval=object()),
        capability_runtime=_runtime(),
        semantic_session_factory=lambda conversation: SemanticSessionComponents(
            conversation=conversation,
            producer=delayed,
            authorization_binding=lambda: "live-grant",
            timeout_seconds=20,
        ),
    )
    _, bridge = controller._session_factory(config)
    bridge.conversation.start()
    attachment = controller._semantic_context_attachment
    try:
        source = bridge.conversation.accept_turn(ConversationRole.USER, "Nepal trip")
        assert attachment.pipeline.submit(source)
        await attachment.pipeline.drain()
        assert attachment.state.active_topic == "Nepal trip"
        assert attachment.pipeline.status.failures == 0
    finally:
        attachment.close()
        await attachment.wait_closed()


def test_controller_rejects_mixed_factory_and_direct_injection():
    with pytest.raises(ValueError, match="choose semantic"):
        CanonicalActiveSpeakerRuntimeController(
            JarvisConfig(),
            SimpleNamespace(output=None),
            semantic_session_factory=lambda _: None,
            semantic_producer=producer,
        )


def test_controller_requires_canonical_authority_for_factory():
    with pytest.raises(ValueError, match="canonical memory and authority"):
        CanonicalActiveSpeakerRuntimeController(
            JarvisConfig(),
            SimpleNamespace(output=None),
            semantic_session_factory=lambda _: None,
        )
