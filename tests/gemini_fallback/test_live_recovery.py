from types import SimpleNamespace

import pytest
from google.genai.errors import APIError
from livekit.agents import ConversationItemAddedEvent, llm
from tests.gemini_fallback.test_live_handoff import setup

from jarvis.provider_resilience import classify_provider_failure


@pytest.mark.asyncio
@pytest.mark.parametrize("busy", ["input", "output", "tool"])
async def test_free_recovery_defers_until_safe_boundary_and_creates_no_health_generation(
    tmp_path, monkeypatch, busy
):
    session, bridge, _, handoff, models, _, _ = await setup(tmp_path, monkeypatch)
    try:
        assert await handoff.handle_failure(
            classify_provider_failure(APIError(429, {}), provider="gemini")
        )
        free = next(
            t for t in handoff.router.target_registry.all() if ".free." in t.target_id
        )
        handoff.runtime.clock = lambda: 200
        handoff.router._clock = handoff.runtime.clock
        if busy == "input":
            handoff._user_state(SimpleNamespace(new_state="speaking"))
        elif busy == "output":
            handoff._agent_state(SimpleNamespace(new_state="speaking"))
        else:
            handoff._pending_tools.add("not-yet-completed")
        assert not await handoff.maybe_recover_free()
        assert len(models) == 1
        handoff._user_state(SimpleNamespace(new_state="listening"))
        handoff._agent_state(SimpleNamespace(new_state="listening"))
        handoff._pending_tools.clear()
        original = bridge.conversation.turns
        assert await handoff.maybe_recover_free()
        assert len(models) == 2
        assert models[-1][1].sessions[0].replies == 0
        assert bridge.conversation.turns == original
        # A successful connection has not proved model availability.
        assert (
            handoff.runtime.store.get_health(free.target_id).consecutive_failures == 1
        )
        session.emit(
            "conversation_item_added",
            ConversationItemAddedEvent(
                item=llm.ChatMessage(
                    role="assistant", content=["A real accepted result"]
                )
            ),
        )
        assert (
            handoff.runtime.store.get_health(free.target_id).consecutive_failures == 0
        )
        assert not await handoff.maybe_recover_free()
        assert len(models) == 2
    finally:
        handoff.close()
        await session.aclose()
