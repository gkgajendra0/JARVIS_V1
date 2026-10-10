"""Voice cancellation requires an explicit owner turn and a listed exact goal."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.test_gicc_composition import _conversation, _store
from jarvis.conversation import ConversationRole
from jarvis.goal_intelligence.composition import GoalIntelligenceCoordinator
from jarvis.voice.gicc_tools import GiccAgentTools


@pytest.mark.asyncio
async def test_voice_cancel_uses_listed_exact_goal_and_explicit_owner_turn(tmp_path):
    store = _store(tmp_path)
    conversation, _ = _conversation("What is the TV task status?")
    target = "goal_tv_status"
    calls = []

    async def cancel(goal_id):
        calls.append(goal_id)
        return {
            "status": "cancelled",
            "goal_id": goal_id,
            "historical_audit_retained": True,
        }

    status = SimpleNamespace(
        list_active=lambda limit: (
            SimpleNamespace(goal_id=target, public_payload=lambda: {"goal_id": target}),
        ),
    )
    runtime = SimpleNamespace(
        pursue=lambda **kwargs: None,
        continue_goal=lambda goal_id: None,
        cancel_owner_goal=cancel,
    )
    tools = GiccAgentTools(
        object.__new__(GoalIntelligenceCoordinator),
        conversation,
        store,
        objective_status=status,
        execution_runtime=runtime,
    )

    # Listing presents exactly one active objective, but does not authorize
    # cancellation until a fresh explicit owner cancellation turn.
    listed = await tools.list_owner_objectives(None)
    assert listed["objectives"] == [{"goal_id": target}]
    assert (await tools.cancel_owner_goal(None, target))["status"] == (
        "explicit_cancel_request_required"
    )
    assert not calls

    conversation.accept_turn(ConversationRole.USER, "Cancel my old TV request.")
    rejected = await tools.cancel_owner_goal(None, "goal_unrelated")
    assert rejected["status"] == "unverified_cancel_target"
    assert not calls

    result = await tools.cancel_owner_goal(None, target)
    assert result["ok"] is True
    assert result["historical_audit_retained"] is True
    assert calls == [target]

    # Old model-selected IDs are not valid after successful cancellation.
    assert (await tools.cancel_owner_goal(None, target))["status"] == (
        "unverified_cancel_target"
    )


@pytest.mark.asyncio
async def test_voice_cancellation_does_not_target_wrong_active_goal(tmp_path):
    store = _store(tmp_path)
    conversation, _ = _conversation("Show my existing requests")
    goals = (
        {"goal_id": "goal_television", "owner_request": "Acquire TV control"},
        {"goal_id": "goal_gate", "owner_request": "Monitor my entrance gate"},
    )
    recorded = []

    async def cancel(goal_id):
        recorded.append(goal_id)
        return {"status": "cancelled", "goal_id": goal_id}

    status = SimpleNamespace(
        list_active=lambda limit: tuple(
            SimpleNamespace(public_payload=lambda item=item: item) for item in goals
        ),
    )
    runtime = SimpleNamespace(
        pursue=lambda **kwargs: None,
        continue_goal=lambda goal_id: None,
        cancel_owner_goal=cancel,
    )
    tools = GiccAgentTools(
        object.__new__(GoalIntelligenceCoordinator),
        conversation,
        store,
        objective_status=status,
        execution_runtime=runtime,
    )
    await tools.list_owner_objectives(None)

    conversation.accept_turn(ConversationRole.USER, "Cancel my old TV request.")
    rejected = await tools.cancel_owner_goal(None, "goal_gate")
    assert rejected["status"] == "ambiguous_cancel_target"
    assert not recorded

    result = await tools.cancel_owner_goal(None, "goal_television")
    assert result["ok"] is True
    assert recorded == ["goal_television"]


@pytest.mark.asyncio
async def test_voice_negated_cancellation_does_not_stop_a_goal(tmp_path):
    store = _store(tmp_path)
    conversation, _ = _conversation("What is my active goal?")
    recorded = []

    async def cancel(goal_id):
        recorded.append(goal_id)
        return {"status": "cancelled", "goal_id": goal_id}

    status = SimpleNamespace(
        list_active=lambda limit: (
            SimpleNamespace(public_payload=lambda: {"goal_id": "goal_tv"}),
        ),
    )
    tools = GiccAgentTools(
        object.__new__(GoalIntelligenceCoordinator),
        conversation,
        store,
        objective_status=status,
        execution_runtime=SimpleNamespace(
            pursue=lambda **kwargs: None,
            continue_goal=lambda goal_id: None,
            cancel_owner_goal=cancel,
        ),
    )
    await tools.list_owner_objectives(None)
    conversation.accept_turn(ConversationRole.USER, "Don't cancel my TV request.")
    result = await tools.cancel_owner_goal(None, "goal_tv")
    assert result["status"] == "cancellation_negated"
    assert not recorded
