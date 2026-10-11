"""Natural typed JARVIS turns route to real tools, never model-granted authority."""

from __future__ import annotations

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.owner_text_chat import OwnerNaturalTextChat
from jarvis.owner_text_console import OwnerTextConversation

pytestmark = pytest.mark.asyncio


class Model:
    def __init__(self, route, target="", message="I'm here.", selected=""):
        self.selected = selected
        self.route = route
        self.target = target
        self.message = message
        self.seen = []

    async def parse(self, *, system_prompt, input_payload, response_model):
        self.seen.append(input_payload)
        return response_model(
            route=self.route,
            target_id=self.target,
            selected_value=self.selected,
            message=self.message,
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
            "ok": True,
            "status": "found",
            "goal_id": goal_id,
            "goal_state": "waiting_capability",
            "phase": "developing",
            "verified_completion": False,
        }

    async def cancel_owner_goal(self, _context, goal_id):
        self.calls.append(("cancel", goal_id))
        return {"ok": True, "status": "cancelled", "goal_id": goal_id}

    async def resolve_goal_information(self, _context, interaction_id, value):
        self.calls.append(("answer_information", interaction_id))
        self.last_value = value
        return {
            "ok": True,
            "status": "waiting_capability",
            "goal_id": "goal_tv",
            "goal_state": "waiting_capability",
        }

    async def offer_bounded_network_discovery(self, _context, goal_id):
        self.calls.append(("offer_discovery", goal_id))
        return {
            "ok": True,
            "status": "discovery_scope_offered",
            "goal_id": goal_id,
            "network_discovery": {
                "summary": "Allow one scoped UPnP observation on the private LAN",
                "protocol": "upnp",
                "result_address_filters": ["192.168.1.0/24"],
                "all_local_interfaces": True,
            },
        }

    async def authorize_bounded_network_discovery(self, _context, goal_id):
        self.calls.append(("approve_discovery", goal_id))
        return {"ok": True, "status": "waiting_information", "goal_id": goal_id}

    async def pursue_owner_goal(self, _context):
        self.calls.append(("pursue", None))
        return {
            "ok": True,
            "status": "waiting_capability",
            "goal_id": "goal_new",
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
    chat = OwnerNaturalTextChat(console=console, conversation=session, client=brain)
    return chat, goals, work, session, brain


def _goal(goal_id, title):
    return {
        "goal_id": goal_id,
        "owner_request": title,
        "desired_outcome": title,
        "terminal": False,
        "goal_state": "waiting_capability",
    }


def test_goal_status_displays_all_canonical_fields() -> None:
    result = {
        "ok": True,
        "goal_id": "goal_tv",
        "owner_request": "Control my television",
        "desired_outcome": "Turn the TV on",
        "goal_state": "waiting_information",
        "overall_state": "waiting_owner",
        "phase": "waiting_information",
        "verified_completion": False,
        "blocker": {
            "kind": "information_need",
            "detail": "Confirm which device is the TV",
            "owner_action_required": True,
        },
        "capability_gap_ids": ["gap_1"],
        "continuation_ids": ["continuation_1"],
        "work": [{"work_id": "work_1", "state": "waiting_owner"}],
        "engineering_changes": [{"change_id": "change_1", "state": "proposed"}],
    }
    answer = OwnerNaturalTextChat._show("inspect_goal", result)
    for detail in (
        "Control my television",
        "Turn the TV on",
        "waiting_owner",
        "Confirm which device is the TV",
        "Owner action required: True",
        "gap_1",
        "continuation_1",
        "work_1",
        "change_1",
    ):
        assert detail in answer


def test_all_clarifications_and_full_gate_proposal_are_visible() -> None:
    questions = [
        {
            "interaction_id": "interaction_a",
            "question": "Which TV?",
            "options": [{"value": "living_room"}],
        },
        {
            "interaction_id": "interaction_b",
            "question": "Which input?",
            "options": [{"value": "hdmi_1"}],
        },
    ]
    response = OwnerNaturalTextChat._show(
        "create_goal",
        {"ok": True, "goal_id": "goal_tv", "questions": questions},
    )
    assert "Which TV?" in response
    assert "Which input?" in response
    assert "interaction_a" in response
    assert "interaction_b" in response
    proposal = "Detailed owner-review evidence: " + "X" * 1500
    gate_response = OwnerNaturalTextChat._show(
        "list_gates",
        {
            "ok": True,
            "gates": [
                {
                    "kind": "architecture",
                    "gate_id": "gate_0123456789abcdef",
                    "change_id": "change_1",
                    "artifact_digest": "digest_1",
                    "proposal": proposal,
                }
            ],
        },
    )
    assert proposal in gate_response


async def test_existing_goal_device_identification_offers_scope_not_new_goal() -> None:
    chat, goals, _, _, _ = _chat(
        "offer_discovery",
        [_goal("goal_tv", "Acquire TV control")],
        "goal_tv",
    )
    result = await chat.submit(
        "Jarvis, identify my TV automatically; show the discovery scope"
    )
    assert result["ok"] is True
    assert result["operation"] == "offer_discovery"
    assert "192.168.1.0/24" in result["message"]
    assert "Windows Hello" in result["message"]
    assert ("offer_discovery", "goal_tv") in goals.calls
    assert not any(action == "pursue" for action, _ in goals.calls)


async def test_offering_unlisted_goal_fails_without_runtime_action() -> None:
    chat, goals, _, _, _ = _chat(
        "offer_discovery",
        [_goal("goal_tv", "Acquire TV control")],
        "goal_unlisted",
    )
    result = await chat.submit("Jarvis, please identify my TV")
    assert result["ok"] is False
    assert not any(action == "offer_discovery" for action, _ in goals.calls)


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


async def test_followup_information_only_accepts_prior_offered_candidate() -> None:
    chat, goals, _, _, brain = _chat("answer_information", target="interaction_123")
    chat.pending_information["interaction_123"] = ("entity_tv1", "entity_tv2")
    brain.selected = "entity_tv2"
    result = await chat.submit("The second TV is mine")
    assert result["ok"] is True
    assert ("answer_information", "interaction_123") in goals.calls
    assert goals.last_value == "entity_tv2"
    assert "interaction_123" not in chat.pending_information


async def test_model_cannot_invent_unoffered_information_value() -> None:
    chat, goals, _, _, brain = _chat("answer_information", target="interaction_123")
    chat.pending_information["interaction_123"] = ("entity_tv1",)
    brain.selected = "entity_hallucinated"
    result = await chat.submit("I want the other one")
    assert result["ok"] is False
    assert not any(a == "answer_information" for a, _ in goals.calls)


async def test_discovery_cannot_be_approved_from_vague_assent() -> None:
    chat, goals, _, _, _ = _chat(
        "approve_discovery", [_goal("goal_tv", "Control my TV")], "goal_tv"
    )
    result = await chat.submit("Yes, go ahead")
    assert result["ok"] is False
    assert not any(a == "approve_discovery" for a, _ in goals.calls)


async def test_explicit_network_discovery_routes_to_governed_tool() -> None:
    chat, goals, _, _, _ = _chat(
        "approve_discovery", [_goal("goal_tv", "Control my TV")], "goal_tv"
    )
    result = await chat.submit("I approve the network discovery")
    assert result["ok"] is True
    assert ("approve_discovery", "goal_tv") in goals.calls
