import uuid
from datetime import UTC, datetime

import pytest

from jarvis.conversation import (
    ConversationRole,
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
)


def test_session_accepts_ordered_turns_while_active() -> None:
    session = ConversationSession()
    session.start()

    first = session.accept_turn(ConversationRole.USER, "  Hello  ")
    second = session.accept_turn(ConversationRole.ASSISTANT, "Hi.")

    assert session.status is ConversationStatus.ACTIVE
    assert [turn.text for turn in session.turns] == ["Hello", "Hi."]
    assert uuid.UUID(session.session_id).version == 4
    assert uuid.UUID(first.turn_id).version == 4
    assert uuid.UUID(second.turn_id).version == 4
    assert first.turn_id != second.turn_id
    assert first.accepted_at.tzinfo is UTC
    assert second.accepted_at.tzinfo is UTC


def test_session_id_is_stable_and_can_be_supplied_by_jarvis_boundary() -> None:
    generated = ConversationSession()
    first_read = generated.session_id
    assert generated.session_id == first_read

    supplied = ConversationSession(session_id="session-test-id")
    assert supplied.session_id == "session-test-id"

    with pytest.raises(ValueError):
        ConversationSession(session_id="   ")
    with pytest.raises(TypeError):
        ConversationSession(session_id=123)  # type: ignore[arg-type]


def test_session_lifecycle_distinguishes_close_and_failure() -> None:
    closed = ConversationSession()
    closed.start()
    closed.close()
    closed.close()
    assert closed.status is ConversationStatus.CLOSED

    failed = ConversationSession()
    failed.start()
    failed.fail()
    failed.close()
    failed.fail()
    assert failed.status is ConversationStatus.FAILED


@pytest.mark.parametrize("status_change", ["none", "close", "fail"])
def test_turns_are_rejected_outside_active_state(status_change: str) -> None:
    session = ConversationSession()
    if status_change != "none":
        session.start()
        getattr(session, status_change)()

    with pytest.raises(RuntimeError):
        session.accept_turn(ConversationRole.USER, "hello")


def test_session_cannot_start_twice() -> None:
    session = ConversationSession()
    session.start()

    with pytest.raises(RuntimeError):
        session.start()


def test_turn_rejects_empty_text_and_invalid_role() -> None:
    with pytest.raises(ValueError):
        ConversationTurn(ConversationRole.USER, "  ")
    with pytest.raises(TypeError):
        ConversationTurn("user", "hello")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ConversationTurn(ConversationRole.USER, None)  # type: ignore[arg-type]


def test_turn_requires_aware_timestamp_and_normalizes_to_utc() -> None:
    naive = datetime(2026, 9, 5, 5, 0, tzinfo=UTC).replace(tzinfo=None)
    with pytest.raises(ValueError):
        ConversationTurn(
            ConversationRole.USER,
            "hello",
            accepted_at=naive,
        )

    offset = datetime.fromisoformat("2026-09-05T10:30:00+05:30")
    turn = ConversationTurn(ConversationRole.USER, "hello", accepted_at=offset)
    assert turn.accepted_at == datetime(2026, 9, 5, 5, 0, tzinfo=UTC)
    assert turn.accepted_at.tzinfo is UTC


def test_external_item_id_is_optional_diagnostic_metadata() -> None:
    session = ConversationSession()
    session.start()
    turn = session.accept_turn(
        ConversationRole.USER,
        "hello",
        external_item_id=" provider-item-1 ",
    )

    assert turn.external_item_id == "provider-item-1"
    assert turn.turn_id != turn.external_item_id

    with pytest.raises(ValueError):
        session.accept_turn(
            ConversationRole.USER,
            "hello again",
            external_item_id="   ",
        )


def test_only_assistant_turn_can_be_interrupted() -> None:
    turn = ConversationTurn(ConversationRole.ASSISTANT, "Partial", interrupted=True)
    assert turn.interrupted is True

    with pytest.raises(ValueError):
        ConversationTurn(ConversationRole.USER, "Stop", interrupted=True)
