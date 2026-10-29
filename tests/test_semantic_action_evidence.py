"""Semantic transitions require explicit positive owner statements."""

from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.conversation_semantics import (
    SemanticAction,
    SemanticContextEngine,
    SemanticProposal,
    SemanticRejected,
)


def _turn(conversation: ConversationSession, text: str):
    return conversation.accept_turn(ConversationRole.USER, text)


def _patch(text: str, action: SemanticAction, *, key: str = ""):
    return SemanticProposal(
        action=action,
        quote=text,
        start=0,
        end=len(text),
        key=key,
    )


def _session_with_route():
    c = ConversationSession()
    c.start()
    e = SemanticContextEngine()
    topic = _turn(c, "Nepal trip")
    e.apply(
        c,
        topic,
        [
            SemanticProposal(
                action=SemanticAction.TOPIC,
                quote=topic.text,
                start=0,
                end=len(topic.text),
                value="Nepal trip",
            )
        ],
        epoch=e.epoch,
    )
    step = _turn(c, "We need to plan the route")
    e.apply(
        c,
        step,
        [
            SemanticProposal(
                action=SemanticAction.PENDING_STEP,
                quote=step.text,
                start=0,
                end=len(step.text),
                key="route",
                value="plan the route",
            )
        ],
        epoch=e.epoch,
    )
    return c, e


@pytest.mark.parametrize(
    "statement",
    (
        "Is the route complete?",
        "The route is not complete",
        "We should complete the route",
        "Can we mark the route done?",
        "I will finish the route tomorrow",
        "The route is planned नहीं",
    ),
)
def test_unconfirmed_route_never_marked_completed(statement: str):
    c, e = _session_with_route()
    turn = _turn(c, statement)
    with pytest.raises(SemanticRejected, match="explicit confirmed state"):
        e.apply(
            c,
            turn,
            [_patch(statement, SemanticAction.COMPLETE_STEP, key="route")],
            epoch=e.epoch,
        )
    assert dict(e.snapshot().steps)["route"].completed is False


@pytest.mark.parametrize(
    "statement",
    (
        "The route is already planned",
        "The route is done",
        "Our route is complete",
        "Route पूरा हो गया",
    ),
)
def test_only_positive_route_completion_is_accepted(statement: str):
    c, e = _session_with_route()
    turn = _turn(c, statement)
    e.apply(
        c,
        turn,
        [_patch(statement, SemanticAction.COMPLETE_STEP, key="route")],
        epoch=e.epoch,
    )
    assert dict(e.snapshot().steps)["route"].completed is True


@pytest.mark.parametrize(
    "statement",
    (
        "Are we still discussing the Nepal trip?",
        "Don't forget Nepal trip",
        "Do not delete Nepal trip",
        "Never remove Nepal trip",
        "Nepal trip mat bhool",
        "नेपाल trip मत भूलना",
        "Can we remove Nepal trip?",
    ),
)
def test_casual_mentions_and_negated_forgets_do_not_delete(statement: str):
    c, e = _session_with_route()
    turn = _turn(c, statement)
    with pytest.raises(SemanticRejected, match="explicit positive"):
        e.apply(
            c,
            turn,
            [_patch(statement, SemanticAction.FORGET_TOPIC)],
            epoch=e.epoch,
        )
    assert e.snapshot("Nepal trip") is not None


@pytest.mark.parametrize(
    "statement",
    (
        "Forget Nepal trip",
        "Delete Nepal trip",
        "Stop remembering Nepal trip",
        "Nepal trip भूल जाओ",
    ),
)
def test_explicit_topic_forgetting_is_accepted(statement: str):
    c, e = _session_with_route()
    turn = _turn(c, statement)
    e.apply(
        c,
        turn,
        [_patch(statement, SemanticAction.FORGET_TOPIC)],
        epoch=e.epoch,
    )
    assert e.snapshot("Nepal trip") is None


@pytest.mark.parametrize(
    "statement",
    (
        "The route is already planned",
        "The route is done",
        "Our route is complete",
        "Route पूरा हो गया",
    ),
)
def test_completion_succeeds_when_windows_gives_turns_identical_timestamps(
    statement: str,
):
    c, e = _session_with_route()
    route = dict(e.snapshot().steps)["route"]
    completion = _turn(c, statement)
    # Reproduce Windows wall-clock resolution: two distinct accepted user turns
    # may share a timestamp. Their canonical user generations still differ.
    completion = replace(completion, accepted_at=route.accepted_at)
    c._turns[-1] = completion
    changed = e.apply(
        c,
        completion,
        [_patch(statement, SemanticAction.COMPLETE_STEP, key="route")],
        epoch=e.epoch,
    )
    assert changed == 1
    field = dict(e.snapshot().steps)["route"]
    assert field.completed is True
    assert field.source_turn_id == completion.turn_id


def test_same_timestamp_old_async_turn_cannot_override_newer_generation():
    c, e = _session_with_route()
    route = dict(e.snapshot().steps)["route"]
    old = _turn(c, "The route is done")
    newer = _turn(c, "The route is done")
    old = replace(old, accepted_at=route.accepted_at)
    newer = replace(newer, accepted_at=route.accepted_at)
    c._turns[-2:] = [old, newer]
    assert e.apply(
        c,
        newer,
        [_patch(newer.text, SemanticAction.COMPLETE_STEP, key="route")],
        epoch=e.epoch,
    ) == 1
    with pytest.raises(SemanticRejected, match="stale asynchronous turn"):
        e.apply(
            c,
            old,
            [_patch(old.text, SemanticAction.COMPLETE_STEP, key="route")],
            epoch=e.epoch,
        )
    assert dict(e.snapshot().steps)["route"].source_turn_id == newer.turn_id
