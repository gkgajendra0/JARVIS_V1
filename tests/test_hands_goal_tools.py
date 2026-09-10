from __future__ import annotations

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


def test_voice_exposes_one_hands_specialist_tool() -> None:
    conversation = ConversationSession(session_id="hands-tool-surface")
    conversation.start()
    tools = HandsGoalAgentTools(
        runtime(), conversation, orchestrator=FakeOrchestrator()
    )

    assert [tool.id for tool in tools.tools] == ["use_computer"]
