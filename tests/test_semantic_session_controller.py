"""Per-wake semantic factories run through the canonical voice controller."""

from types import SimpleNamespace

import pytest
from test_long_utterance_activity import _session_pair
from test_production_hands_voice_wiring import _runtime

from jarvis.config import JarvisConfig
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
