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

    session.accept_turn(ConversationRole.USER, "  Hello  ")
    session.accept_turn(ConversationRole.ASSISTANT, "Hi.")

    assert session.status is ConversationStatus.ACTIVE
    assert [turn.text for turn in session.turns] == ["Hello", "Hi."]


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


def test_only_assistant_turn_can_be_interrupted() -> None:
    turn = ConversationTurn(ConversationRole.ASSISTANT, "Partial", interrupted=True)
    assert turn.interrupted is True

    with pytest.raises(ValueError):
        ConversationTurn(ConversationRole.USER, "Stop", interrupted=True)
