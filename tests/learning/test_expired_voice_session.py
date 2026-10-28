"""Real memory authority with fake Windows/Hello; no provider requests."""

import asyncio
from types import SimpleNamespace

import pytest
from context_query_helpers import context_session, seed_item
from livekit.agents import llm
from tests.gemini_fallback.live_helpers import ProviderModel

from jarvis.config import JarvisConfig
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.voice.gemini_transport import (
    GeminiTransportState,
    GuardedGeminiRealtimeModel,
)


def controller_for(personal, conversation, harness):
    c = CanonicalActiveSpeakerRuntimeController(JarvisConfig(), SimpleNamespace())
    c._session_conversation = conversation
    c._active_end = asyncio.Event()
    c._personal_context = personal
    c._learning_authority = harness.authority
    c._learning_grant = harness.grant
    return c, SimpleNamespace(conversation=conversation)


@pytest.mark.asyncio
async def test_fresh_ordinary_transport_works_after_long_idle(
    learning, clock, authority_parts
):
    async with context_session(learning, history="ordinary previous turn") as (
        personal,
        conversation,
        retired,
    ):
        controller, bridge = controller_for(personal, conversation, learning)
        clock.advance(901)
        raw = ProviderModel()
        model = GuardedGeminiRealtimeModel(
            raw,
            GeminiTransportState(
                epoch=0,
                current_epoch=lambda: 0,
                authorize=lambda: controller._validate_gemini_handoff(bridge),
            ),
        )
        session = model.session()
        try:
            await session.update_instructions("ordinary conversation instructions")
            await session.update_chat_ctx(llm.ChatContext.empty())
            await session.update_tools([])
            assert raw.sessions[0].instructions == "ordinary conversation instructions"
            assert not retired
            assert len(authority_parts.hello.calls) == 1
        finally:
            await session.aclose()


@pytest.mark.asyncio
async def test_long_idle_memory_query_still_returns_facts(
    learning, clock, authority_parts
):
    await seed_item(learning)
    async with context_session(learning) as (personal, _, retired):
        clock.advance(901)
        result = await personal.query_for_question(
            [{"scope_key": "owned_item.vehicle"}]
        )
        assert result["status"] == "selected"
        assert result["facts"]
        assert not retired
        assert await personal.allow_audio()
        assert learning.authority.validate(learning.grant).status == "active"
        assert len(authority_parts.hello.calls) == 1


@pytest.mark.asyncio
async def test_short_read_lease_expiry_still_blocks_private_context_and_audio(
    learning, clock, authority_parts
):
    await seed_item(learning)
    async with context_session(learning) as (personal, conversation, retired):
        result = await personal.query_for_question(
            [{"scope_key": "owned_item.vehicle"}]
        )
        assert result["status"] == "selected"
        controller, bridge = controller_for(personal, conversation, learning)
        clock.advance(901)
        assert not await controller._validate_gemini_handoff(bridge)
        assert not await personal.allow_audio()
        assert retired
        assert len(authority_parts.hello.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("expire_first", [False, True])
async def test_windows_security_revocation_still_blocks_transport_and_audio(
    learning, clock, authority_parts, expire_first
):
    async with context_session(learning) as (personal, conversation, retired):
        controller, bridge = controller_for(personal, conversation, learning)
        if expire_first:
            clock.advance(901)
        authority_parts.windows.lock_unlock()
        assert not await controller._validate_gemini_handoff(bridge)
        result = await personal.query_for_question(
            [{"scope_key": "owned_item.vehicle"}]
        )
        assert result["status"] == "denied"
        assert retired
        assert not await personal.allow_audio()
        assert len(authority_parts.hello.calls) == 1
