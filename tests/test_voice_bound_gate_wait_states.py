from __future__ import annotations

from jarvis.voice.work_tools import _bound_gate_conflict_payload


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
