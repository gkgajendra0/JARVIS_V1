"""Owner text ingress must use canonical goal tools, not simulated mutations."""

from __future__ import annotations

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.owner_text_console import OwnerTextConversation

pytestmark = pytest.mark.asyncio


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


async def test_plain_goal_prefix_submits_original_outcome():
    console, fake, session = _console()
    result = await console.submit("goal Open Hotstar on my TV")
    assert result["status"] == "waiting_capability"
    assert fake.calls == [("pursue", None)]
    assert session.turns[-1].text == "Open Hotstar on my TV"


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


class FakeWorkTools:
    def __init__(self):
        self.calls: list[tuple[str, str | None]] = []

    async def decide_change_gate(self, context, gate_id):
        self.calls.append(("decision", gate_id))
        return {"ok": True, "status": "decided", "gate_id": gate_id}

    async def continue_background_work(self, context, work_id):
        self.calls.append(("answer", work_id))
        return {"ok": True, "status": "owner_input_submitted", "work_id": work_id}

    async def list_background_work(self, context):
        self.calls.append(("work_list", None))
        return {"ok": True, "status": "work_listed", "work": []}

    async def get_background_work_status(self, context, work_id):
        self.calls.append(("work_status", work_id))
        return {"ok": True, "status": "found", "work_id": work_id}


class FakeGates:
    def __init__(self, gate_ids, *, kind="architecture"):
        from types import SimpleNamespace

        self.ids = list(gate_ids)
        self.kind = kind
        self.store = SimpleNamespace(
            get_artifact=lambda _key: SimpleNamespace(
                payload={"summary": "Review exact architecture"}
            )
        )

    def pending_gate_ids(self):
        return tuple(self.ids)

    def get(self, gate_id):
        from types import SimpleNamespace

        if gate_id not in self.ids:
            return None
        return SimpleNamespace(
            gate_id=gate_id,
            artifact_id="artifact_test1",
            change_id="change_test1",
            artifact_digest="sha256",
            kind=SimpleNamespace(value=self.kind),
        )


async def test_governed_gate_decision_requires_prior_listing_and_exact_id():
    console, fake, session = _console()
    work = FakeWorkTools()
    gate_id = "gate_0123456789abcdef"
    gates = FakeGates([gate_id])
    console._work_tools = work
    console._gates = gates

    rejected = await console.submit(f"approve {gate_id}")
    assert rejected["status"] == "gate_not_reviewed_in_current_text_session"
    assert work.calls == []

    listed = await console.submit("gates")
    assert listed["gates"][0]["gate_id"] == gate_id
    assert listed["gates"][0]["approval_requires_windows_hello"] is True
    result = await console.submit(f"approve {gate_id}")
    assert result["status"] == "decided"
    assert work.calls == [("decision", gate_id)]
    assert session.turns[-1].text == f"approve {gate_id}"


async def test_text_gate_review_rejects_stale_or_promotion_gates():
    console, _, _ = _console()
    work = FakeWorkTools()
    gate_id = "gate_0123456789abcdef"
    gates = FakeGates([gate_id])
    console._work_tools = work
    console._gates = gates
    await console.submit("gates")
    gates.ids.clear()
    assert (await console.submit(f"reject {gate_id}"))[
        "status"
    ] == "gate_no_longer_pending"
    gates.ids.append(gate_id)
    gates.kind = "promotion"
    await console.submit("gates")
    assert (await console.submit(f"approve {gate_id}"))[
        "status"
    ] == "promotion_approval_requires_dedicated_governed_path"
    assert work.calls == []


async def test_text_owner_input_passes_only_answer_as_canonical_turn():
    console, _, session = _console()
    work = FakeWorkTools()
    console._work_tools = work
    result = await console.submit("answer work_0123456789abcdef: TV is powered on")
    assert result["status"] == "owner_input_submitted"
    assert session.turns[-1].text == "TV is powered on"
    assert work.calls == [("answer", "work_0123456789abcdef")]


async def test_text_work_status_is_real_work_tool():
    console, _, _ = _console()
    work = FakeWorkTools()
    console._work_tools = work
    assert (await console.submit("work"))["status"] == "work_listed"
    assert (await console.submit("work work_0123456789abcdef"))["status"] == "found"
    assert work.calls == [
        ("work_list", None),
        ("work_status", "work_0123456789abcdef"),
    ]


async def test_unrecognized_chat_does_not_accidentally_create_goal():
    console, fake, _ = _console()
    response = await console.submit("What is the weather?")
    assert response["status"] == "explicit_goal_prefix_required"
    assert fake.calls == []
