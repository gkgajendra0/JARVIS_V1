from __future__ import annotations

import asyncio

import pytest

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.voice.hands_goal_tools import HandsGoalAgentTools
from jarvis.voice.hands_latency_tool import LatencyOptimizedHandsGoalAgentTools


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
async def test_voice_hands_waits_for_current_transcript_instead_of_using_old_turn() -> (
    None
):
    conversation = ConversationSession(session_id="hands-wait")
    conversation.start()
    old = conversation.accept_turn(ConversationRole.USER, "Set volume to 35 percent")
    activity_epoch = conversation.begin_user_activity()

    assert old.user_activity_epoch is None
    assert activity_epoch == 1
    assert conversation.user_utterance_generation == 1

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

    assert latest.user_activity_epoch == activity_epoch
    assert result["ok"] is True
    assert result["canonical_user_turn_id"] == latest.turn_id
    assert fake.calls[0]["goal"] == "Open Apple Music"


@pytest.mark.asyncio
async def test_newer_voice_activity_supersedes_call_waiting_for_old_transcript() -> (
    None
):
    conversation = ConversationSession(session_id="hands-supersede-pending")
    conversation.start()
    conversation.begin_user_activity()
    tools = HandsGoalAgentTools(
        runtime(),
        conversation,
        orchestrator=FakeOrchestrator(),
        transcript_wait_seconds=0.5,
    )

    pending = asyncio.create_task(tools.execute_goal())
    await asyncio.sleep(0.03)
    conversation.begin_user_activity()
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tools_type", [HandsGoalAgentTools, LatencyOptimizedHandsGoalAgentTools]
)
async def test_missing_transcript_clarifies_once_then_waits_for_new_activity(
    tools_type,
):
    from livekit.agents.llm import StopResponse

    conversation = ConversationSession(session_id="hands-missing-transcript")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "Old instruction")
    conversation.begin_user_activity()
    fake = FakeOrchestrator()
    tools = tools_type(
        runtime(), conversation, orchestrator=fake, transcript_wait_seconds=0.01
    )

    first = await tools.execute_goal()
    assert first["status"] == "clarification_required"
    assert first["reason"] == "canonical_user_transcript_unavailable"
    assert fake.calls == []
    with pytest.raises(StopResponse) as suppressed:
        await tools.execute_goal()
    from livekit.agents import llm
    from livekit.agents.voice.generation import make_tool_output

    output = make_tool_output(
        fnc_call=llm.FunctionCall(
            call_id="duplicate", name="use_computer", arguments="{}"
        ),
        output=None,
        exception=suppressed.value,
    )
    assert output.fnc_call_out.reply_required is False
    assert output.fnc_call_out.is_error is False

    # A late transcript cannot silently rearm a timed-out instruction.
    conversation.accept_turn(ConversationRole.USER, "Late old instruction")
    with pytest.raises(StopResponse):
        await tools.execute_goal()
    assert fake.calls == []

    conversation.begin_user_activity()
    latest = conversation.accept_turn(ConversationRole.USER, "Open Calculator")
    recovered = await tools.execute_goal()
    assert recovered["ok"] is True
    assert recovered["canonical_user_turn_id"] == latest.turn_id
    assert [call["goal"] for call in fake.calls] == ["Open Calculator"]


@pytest.mark.asyncio
async def test_concurrent_missing_transcript_calls_clarify_only_once():
    from livekit.agents.llm import StopResponse

    conversation = ConversationSession(session_id="hands-concurrent-missing")
    conversation.start()
    conversation.begin_user_activity()
    fake = FakeOrchestrator()
    tools = HandsGoalAgentTools(
        runtime(), conversation, orchestrator=fake, transcript_wait_seconds=0.01
    )
    results = await asyncio.gather(
        tools.execute_goal(), tools.execute_goal(), return_exceptions=True
    )
    assert sum(isinstance(result, StopResponse) for result in results) == 1
    assert (
        sum(
            isinstance(result, dict) and result["status"] == "clarification_required"
            for result in results
        )
        == 1
    )
    assert fake.calls == []
