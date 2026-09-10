from __future__ import annotations

import asyncio

import pytest

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.voice.hands_goal_tools import HandsGoalAgentTools


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
        self.calls = []

    async def execute_goal(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "status": "succeeded", "completed_steps": 1}


def runtime() -> CapabilityRuntime:
    return CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=NoopAuthority(),
    )


@pytest.mark.asyncio
async def test_voice_hands_handoff_uses_exact_latest_user_goal_without_plan_json() -> (
    None
):
    conversation = ConversationSession(session_id="hands-handoff")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "Open Apple Music")
    latest = conversation.accept_turn(
        ConversationRole.USER,
        "Could you get FIFA going for me?",
    )
    fake = FakeOrchestrator()
    tools = HandsGoalAgentTools(runtime(), conversation, orchestrator=fake)

    result = await tools.execute_goal()

    assert result["ok"] is True
    assert result["canonical_user_turn_id"] == latest.turn_id
    assert fake.calls == [
        {
            "session_id": "hands-handoff",
            "goal": "Could you get FIFA going for me?",
            "recent_user_turns": ("Open Apple Music",),
        }
    ]


@pytest.mark.asyncio
async def test_voice_hands_waits_for_current_transcript_instead_of_using_old_turn() -> None:
    conversation = ConversationSession(session_id="hands-wait")
    conversation.start()
    old = conversation.accept_turn(ConversationRole.USER, "Set volume to 35 percent")
    generation = conversation.begin_user_utterance()
    assert generation > (old.user_utterance_generation or 0)

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
    latest = conversation.accept_turn(ConversationRole.USER, "Open Apple Music")
    result = await pending

    assert result["ok"] is True
    assert result["canonical_user_turn_id"] == latest.turn_id
    assert fake.calls[0]["goal"] == "Open Apple Music"


@pytest.mark.asyncio
async def test_newer_voice_generation_supersedes_call_waiting_for_old_transcript() -> None:
    conversation = ConversationSession(session_id="hands-supersede-pending")
    conversation.start()
    conversation.begin_user_utterance()
    tools = HandsGoalAgentTools(
        runtime(),
        conversation,
        orchestrator=FakeOrchestrator(),
        transcript_wait_seconds=0.5,
    )

    pending = asyncio.create_task(tools.execute_goal())
    await asyncio.sleep(0.03)
    conversation.begin_user_utterance()
    result = await pending

    assert result["ok"] is False
    assert result["status"] == "superseded"


@pytest.mark.asyncio
async def test_duplicate_hands_call_for_same_voice_turn_is_ignored() -> None:
    conversation = ConversationSession(session_id="hands-duplicate")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "Open Calculator")
    fake = FakeOrchestrator()
    tools = HandsGoalAgentTools(runtime(), conversation, orchestrator=fake)

    first = await tools.execute_goal()
    duplicate = await tools.execute_goal()

    assert first["ok"] is True
    assert duplicate["ok"] is False
    assert duplicate["status"] == "superseded"
    assert len(fake.calls) == 1


def test_voice_exposes_one_hands_specialist_tool() -> None:
    conversation = ConversationSession(session_id="hands-tool-surface")
    conversation.start()
    tools = HandsGoalAgentTools(
        runtime(), conversation, orchestrator=FakeOrchestrator()
    )

    assert [tool.id for tool in tools.tools] == ["use_computer"]
