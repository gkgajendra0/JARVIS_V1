"""Natural typed JARVIS turns route to real tools, never model-granted authority."""

from __future__ import annotations

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.owner_text_chat import OwnerNaturalTextChat, TextChatDecision
from jarvis.owner_text_console import OwnerTextConversation

pytestmark = pytest.mark.asyncio


class Model:
    def __init__(self, route, target="", message="I'm here."):
        self.route = route
        self.target = target
        self.message = message
        self.seen = []

    async def parse(self, *, system_prompt, input_payload, response_model):
        self.seen.append(input_payload)
        return response_model(
            route=self.route, target_id=self.target, message=self.message
        )


class Goals:
    def __init__(self, objectives=()):
        self.objectives = list(objectives)
        self.calls = []

    async def list_owner_objectives(self, _context):
        self.calls.append(("list", None))
        return {"ok": True, "status": "listed", "objectives": self.objectives}

    async def get_owner_objective_status(self, _context, goal_id):
        self.calls.append(("status", goal_id))
        return {
            "ok": True, "status": "found", "goal_id": goal_id,
            "goal_state": "waiting_capability", "phase": "developing",
            "verified_completion": False,
        }

    async def cancel_owner_goal(self, _context, goal_id):
        self.calls.append(("cancel", goal_id))
        return {"ok": True, "status": "cancelled", "goal_id": goal_id}

    async def pursue_owner_goal(self, _context):
        self.calls.append(("pursue", None))
        return {
            "ok": True, "status": "waiting_capability", "goal_id": "goal_new",
            "goal_state": "waiting_capability",
        }


class Work:
    def __init__(self, items=()):
        self.items = list(items)
        self.calls = []

    async def list_background_work(self, _context):
        self.calls.append(("list", None))
        return {"ok": True, "status": "listed", "work": self.items}

    async def get_background_work_status(self, _context, work_id):
        self.calls.append(("status", work_id))
        return {"ok": True, "status": "found", "work_id": work_id, "state": "active"}

    async def continue_background_work(self, _context, work_id):
        self.calls.append(("answer", work_id))
        return {"ok": True, "status": "owner_input_submitted", "work_id": work_id}


def _chat(route, objectives=(), target="", message="I'm here.", work_items=()):
    session = ConversationSession()
    session.start()
    goals = Goals(objectives)
    work = Work(work_items)
    console = OwnerTextConversation(goals, session, work_tools=work)
    brain = Model(route, target=target, message=message)
    chat = OwnerNaturalTextChat(
        console=console, conversation=session, client=brain
    )
    return chat, goals, work, session, brain


def _goal(goal_id, title):
    return {
        "goal_id": goal_id, "owner_request": title,
        "desired_outcome": title, "terminal": False,
        "goal_state": "waiting_capability",
    }


async def test_natural_chat_without_command_prefix() -> None:
    chat, goals, work, session, brain = _chat("respond")
    r = await chat.submit("Hey Jarvis, are you with me?")
    assert r["message"] == "I'm here."
    assert session.turns[-1].text == "Hey Jarvis, are you with me?"
    assert brain.seen[0]["latest_owner_message"] == "Hey Jarvis, are you with me?"
    assert not any(action in {"pursue", "cancel"} for action, _ in goals.calls)
    assert work.calls == [("list", None)]


async def test_goal_status_from_natural_question_not_new_goal() -> None:
    chat, goals, _, session, _ = _chat(
        "inspect_goal", [_goal("goal_tv", "Control my television")], "goal_tv"
    )
    r = await chat.submit("Jarvis, where are we with the television thing?")
    assert "waiting_capability" in r["message"]
    assert ("status", "goal_tv") in goals.calls
    assert session.turns[-1].role is ConversationRole.USER


async def test_natural_goal_without_reserved_prefix_enters_gicc() -> None:
    chat, goals, _, session, _ = _chat("create_goal")
    r = await chat.submit("Please get the TV remote-control capability")
    assert ("pursue", None) in goals.calls
    assert r["operation_status"] == "waiting_capability"
    assert session.turns[-1].text == "Please get the TV remote-control capability"


async def test_model_cannot_cancel_wrong_topic_or_unrelated_goal() -> None:
    chat, goals, _, _, _ = _chat(
        "cancel_goal", [_goal("goal_tv", "Control my TV")], target="goal_tv"
    )
    result = await chat.submit("Please cancel my camera goal")
    assert result["ok"] is False
    assert ("cancel", "goal_tv") not in goals.calls


async def test_model_cannot_cancel_on_discussion_of_cancellation() -> None:
    chat, goals, _, _, _ = _chat(
        "cancel_goal", [_goal("goal_tv", "Control my TV")], target="goal_tv"
    )
    result = await chat.submit("Should we cancel the TV goal?")
    # This is a question, not owner permission; model should answer instead.
    # Regardless of model mistakes, consequential actions need a fresh order.
    assert result["ok"] is False
    assert ("cancel", "goal_tv") not in goals.calls


async def test_exact_cancellation_uses_authoritative_listed_goal() -> None:
    chat, goals, _, session, _ = _chat(
        "cancel_goal", [_goal("goal_tv", "Control my TV")], "goal_tv"
    )
    result = await chat.submit("Cancel the old TV goal")
    assert result["ok"] is True
    assert ("cancel", "goal_tv") in goals.calls
    assert session.turns[-1].text == "Cancel the old TV goal"


async def test_ambiguous_duplicate_target_refuses_execution() -> None:
    chat, goals, _, _, _ = _chat(
        "cancel_goal",
        [_goal("goal_tv1", "Control TV"), _goal("goal_tv2", "Repair television")],
        target="goal_tv1",
    )
    result = await chat.submit("Cancel my TV request")
    assert result["ok"] is False
    assert not any(a == "cancel" for a, _ in goals.calls)


async def test_ai_cannot_approve_gate_without_exact_verified_review() -> None:
    chat, goals, _, _, _ = _chat("review_gate", target="gate_0123456789abcdef")
    result = await chat.submit("yeah sure")
    assert result["ok"] is False
    assert not any(a == "pursue" for a, _ in goals.calls)


async def test_no_new_goal_from_hypothetical_question() -> None:
    chat, goals, _, _, _ = _chat("create_goal")
    result = await chat.submit("What if I wanted TV control?")
    assert result["ok"] is False
    assert not any(a == "pursue" for a, _ in goals.calls)


async def test_duplicate_goal_not_readmitted() -> None:
    text = "Please get the TV remote-control capability"
    chat, goals, _, _, _ = _chat("create_goal", [_goal("goal_tv", text)])
    result = await chat.submit(text)
    assert result["operation_status"] == "existing_active_goal"
    assert not any(a == "pursue" for a, _ in goals.calls)


async def test_model_failure_fails_closed_without_canonical_turn() -> None:
    chat, goals, _, session, brain = _chat("create_goal")
    async def fail(**kwargs):
        raise RuntimeError("model offline")
    brain.parse = fail
    result = await chat.submit("Open my TV app")
    assert result["status"] == "chat_brain_unavailable"
    assert session.turns == ()
    assert not any(a == "pursue" for a, _ in goals.calls)
