"""Owner text ingress must use canonical goal tools, not simulated mutations."""

from __future__ import annotations

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.owner_text_console import OwnerTextConversation


class FakeGoalTools:
    def __init__(self, objectives=None):
        self.objectives = [] if objectives is None else objectives
        self.calls: list[tuple[str, str | None]] = []

    async def list_owner_objectives(self, context):
        self.calls.append(("list", None))
        return {"ok": True, "status": "listed", "objectives": self.objectives}

    async def get_owner_objective_status(self, context, goal_id):
        self.calls.append(("status", goal_id))
        return {"ok": True, "status": "found", "goal_id": goal_id}

    async def cancel_owner_goal(self, context, goal_id):
        self.calls.append(("cancel", goal_id))
        return {"ok": True, "status": "cancelled", "goal_id": goal_id}

    async def pursue_owner_goal(self, context):
        self.calls.append(("pursue", None))
        return {"ok": True, "status": "waiting_capability"}


def _console(objectives=None):
    session = ConversationSession()
    session.start()
    fake = FakeGoalTools(objectives)
    return OwnerTextConversation(fake, session), fake, session


def _objective(goal_id: str, request: str):
    return {
        "goal_id": goal_id,
        "owner_request": request,
        "desired_outcome": request,
        "terminal": False,
    }


async def test_typed_tv_cancellation_reuses_exact_guarded_goal_tool():
    console, fake, conversation = _console(
        [_objective("goal_tv1", "Acquire TV control")]
    )
    result = await console.submit("Cancel my previous TV control request.")
    assert result["status"] == "cancelled"
    assert fake.calls == [("list", None), ("cancel", "goal_tv1")]
    assert conversation.turns[-1].role is ConversationRole.USER
    assert conversation.turns[-1].text == "Cancel my previous TV control request."


async def test_text_cancellation_does_not_guess_with_multiple_tvs():
    console, fake, _ = _console(
        [
            _objective("goal_tv1", "Acquire TV control"),
            _objective("goal_tv2", "Repair Hisense TV"),
        ]
    )
    result = await console.submit("Cancel my previous TV request")
    assert result["status"] == "ambiguous_cancel_target"
    assert fake.calls == [("list", None)]


async def test_text_cancellation_refuses_wrong_device():
    console, fake, _ = _console([_objective("goal_tv1", "Acquire TV control")])
    result = await console.submit("Cancel my camera request")
    assert result["status"] == "ambiguous_cancel_target"
    assert fake.calls == [("list", None)]


async def test_explicit_goal_id_cancel_uses_existing_tool():
    console, fake, _ = _console(
        [
            _objective("goal_tv1", "Acquire TV control"),
            _objective("goal_camera2", "Acquire camera control"),
        ]
    )
    result = await console.submit("cancel goal_camera2")
    assert result["status"] == "cancelled"
    assert fake.calls == [("list", None), ("cancel", "goal_camera2")]


async def test_typed_goal_admitted_to_real_tool():
    console, fake, session = _console()
    result = await console.submit("/goal Open Hotstar on my television")
    assert result["status"] == "waiting_capability"
    assert fake.calls == [("pursue", None)]
    assert session.turns[-1].text == "Open Hotstar on my television"


async def test_status_read_and_list_do_not_create_goal():
    console, fake, _ = _console([_objective("goal_tv1", "Acquire TV control")])
    a = await console.submit("goals")
    b = await console.submit("status goal_tv1")
    assert a["status"] == "listed"
    assert b["status"] == "found"
    assert fake.calls == [("list", None), ("status", "goal_tv1")]


async def test_generic_approval_never_bypasses_authority_or_starts_goal():
    console, fake, _ = _console()
    result = await console.submit("approved")
    assert result["status"] == "approval_requires_bound_context"
    assert fake.calls == []


async def test_help_and_quit_are_local_only():
    console, fake, session = _console()
    assert (await console.submit("help"))["status"] == "help"
    assert (await console.submit("quit"))["status"] == "exit"
    assert fake.calls == []
    assert session.turns == ()
