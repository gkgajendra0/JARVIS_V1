from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.voice.work_tools import WorkAgentTools, _bound_gate_conflict_payload
from jarvis.work.runtime import WorkRuntime


def test_bound_gate_no_owner_turn_is_nonfatal_wait_state() -> None:
    payload = _bound_gate_conflict_payload(
        "no accepted owner turn",
        "gate_0123456789abcdef",
    )

    assert payload == {
        "ok": False,
        "status": "awaiting_owner_turn",
        "gate_id": "gate_0123456789abcdef",
        "message": (
            "No canonical owner decision has been accepted yet. "
            "Keep listening and do not report an internal error."
        ),
    }


def test_bound_gate_unclear_owner_turn_requests_explicit_decision() -> None:
    payload = _bound_gate_conflict_payload(
        "owner must explicitly identify the current gate",
        "gate_0123456789abcdef",
    )

    assert payload == {
        "ok": False,
        "status": "awaiting_explicit_decision",
        "gate_id": "gate_0123456789abcdef",
        "message": (
            "The latest owner turn did not contain an explicit approve/reject "
            "decision. Ask again naturally."
        ),
    }


def test_bound_gate_unexpected_conflict_is_not_hidden() -> None:
    assert (
        _bound_gate_conflict_payload(
            "strong owner verification failed",
            "gate_0123456789abcdef",
        )
        is None
    )



@pytest.mark.asyncio
async def test_bound_gate_success_signals_deterministic_completion_callback() -> None:
    runtime = object.__new__(WorkRuntime)

    class Store:
        def require(self, change_id: str):
            assert change_id == "change_approved"
            return SimpleNamespace(state=SimpleNamespace(value="developing"))

    runtime.changes = SimpleNamespace(store=Store())

    conversation = ConversationSession()
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "approved")

    callbacks: list[bool] = []
    tools = WorkAgentTools(
        runtime,
        conversation,
        bound_change_gate_id="gate_0123456789abcdef",
        on_bound_change_gate_decided=callbacks.append,
        allow_capability_acquisition=False,
    )

    class Service:
        def decide_latest(self, gate_id: str, *, bound_gate_id: str | None = None):
            assert gate_id == "gate_0123456789abcdef"
            assert bound_gate_id == gate_id
            return SimpleNamespace(
                challenge=SimpleNamespace(change_id="change_approved"),
                approved=True,
            )

    tools._change_service = lambda: Service()  # type: ignore[method-assign]

    result = await tools.decide_change_gate(
        None,  # type: ignore[arg-type]
        "gate_0123456789abcdef",
    )

    assert result["ok"] is True
    assert result["approved"] is True
    assert callbacks == [True]
