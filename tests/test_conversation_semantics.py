"""Grounded semantic state: canonical sources, corrections, and privacy boundaries."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.conversation import (
    ConversationRole,
    ConversationSession,
    ConversationStatus,
)
from jarvis.memory.conversation_semantics import (
    EvidenceStrength,
    SemanticAction,
    SemanticContextEngine,
    SemanticProposal,
    SemanticRejected,
)
from jarvis.memory.types import Sensitivity

START = datetime(2026, 10, 29, tzinfo=UTC)


def utterance(session, number, text, role=ConversationRole.USER):
    if session.status is ConversationStatus.CREATED:
        session.start()
    raw = session.accept_turn(role, text)
    accepted = replace(raw, accepted_at=START + timedelta(seconds=number))
    session._turns[-1] = accepted
    return accepted


def proposal(
    text, action, *, value="", key="", topic="", sensitivity=Sensitivity.STANDARD
):
    return SemanticProposal(
        action=action,
        quote=text,
        start=0,
        end=len(text),
        value=value,
        key=key,
        topic=topic,
        sensitivity=sensitivity,
    )


def apply_epoch(engine, conversation, turn, proposals):
    return engine.apply(conversation, turn, proposals, epoch=engine.epoch)


def apply(engine, session, index, text, action, **kwargs):
    turn = utterance(session, index, text)
    return apply_epoch(engine, session, turn, [proposal(text, action, **kwargs)])


def test_nepal_seven_turn_working_state_and_completion():
    session = ConversationSession()
    engine = SemanticContextEngine()
    apply(
        engine,
        session,
        1,
        "Let's discuss my Nepal trip",
        SemanticAction.TOPIC,
        value="Nepal trip",
    )
    apply(
        engine,
        session,
        2,
        "My goal is to plan Nepal",
        SemanticAction.GOAL,
        value="plan Nepal",
    )
    apply(
        engine,
        session,
        3,
        "My vehicle is a Jimny",
        SemanticAction.CONSTRAINT,
        key="vehicle",
        value="Jimny",
    )
    apply(
        engine,
        session,
        4,
        "The permits are sorted",
        SemanticAction.CONSTRAINT,
        key="permits",
        value="sorted",
    )
    apply(
        engine,
        session,
        5,
        "Budget is not a constraint",
        SemanticAction.CONSTRAINT,
        key="budget",
        value="unrestricted",
    )
    apply(
        engine,
        session,
        6,
        "Next, plan the route",
        SemanticAction.PENDING_STEP,
        key="route",
        value="plan route",
    )

    current = engine.snapshot()
    assert current is not None
    assert current.title == "Nepal trip"
    assert dict(current.constraints)["vehicle"].value == "Jimny"
    assert dict(current.constraints)["budget"].value == "unrestricted"
    assert dict(current.steps)["route"].completed is False
    assert (
        dict(current.constraints)["budget"].evidence_strength
        is EvidenceStrength.INTERPRETED
    )

    apply(
        engine,
        session,
        7,
        "Actually the budget is 10000",
        SemanticAction.CORRECT,
        key="budget",
        value="10000",
    )
    assert dict(engine.snapshot().constraints)["budget"].value == "10000"
    apply(
        engine,
        session,
        8,
        "The route is planned",
        SemanticAction.COMPLETE_STEP,
        key="route",
    )
    assert dict(engine.snapshot().steps)["route"].completed is True


def test_topic_switch_does_not_mix_constraints():
    c = ConversationSession()
    e = SemanticContextEngine()
    apply(e, c, 1, "Nepal trip", SemanticAction.TOPIC, value="Nepal trip")
    apply(
        e,
        c,
        2,
        "Permits are sorted",
        SemanticAction.CONSTRAINT,
        key="permits",
        value="sorted",
    )
    apply(
        e,
        c,
        3,
        "Interview preparation",
        SemanticAction.TOPIC,
        value="Interview preparation",
    )
    assert e.snapshot().constraints == ()
    assert dict(e.snapshot("Nepal trip").constraints)["permits"].value == "sorted"


def test_other_topic_cannot_be_modified_implicitly():
    c = ConversationSession()
    e = SemanticContextEngine()
    apply(e, c, 1, "Nepal trip", SemanticAction.TOPIC, value="Nepal trip")
    apply(e, c, 2, "Interview prep", SemanticAction.TOPIC, value="Interview prep")
    t = utterance(c, 3, "Budget unlimited")
    with pytest.raises(SemanticRejected, match="inactive topic"):
        apply_epoch(
            e,
            c,
            t,
            [
                proposal(
                    t.text,
                    SemanticAction.CONSTRAINT,
                    topic="Nepal trip",
                    key="budget",
                    value="unlimited",
                )
            ],
        )


def test_assistant_and_foreign_turns_cannot_create_context():
    c = ConversationSession()
    e = SemanticContextEngine()
    t = utterance(c, 1, "Nepal trip", ConversationRole.ASSISTANT)
    with pytest.raises(SemanticRejected, match="USER"):
        apply_epoch(
            e, c, t, [proposal(t.text, SemanticAction.TOPIC, value="Nepal trip")]
        )
    other = ConversationSession()
    fake = utterance(other, 2, "Nepal trip")
    with pytest.raises(SemanticRejected, match="canonical"):
        apply_epoch(
            e,
            c,
            fake,
            [proposal(fake.text, SemanticAction.TOPIC, value="Nepal trip")],
        )


def test_forged_quote_and_batch_failure_are_atomic():
    c = ConversationSession()
    e = SemanticContextEngine()
    t = utterance(c, 1, "Let's discuss Nepal")
    valid = proposal(t.text, SemanticAction.TOPIC, value="Nepal")
    invalid = replace(valid, quote="France")
    with pytest.raises(SemanticRejected, match="exact user evidence"):
        apply_epoch(e, c, t, [valid, invalid])
    assert e.snapshot() is None


def test_invented_date_rejected_and_other_updates_not_applied():
    c = ConversationSession()
    e = SemanticContextEngine()
    apply(e, c, 1, "Nepal trip", SemanticAction.TOPIC, value="Nepal trip")
    t = utterance(c, 2, "My documents are sorted")
    with pytest.raises(SemanticRejected, match="unquoted numerical"):
        apply_epoch(
            e,
            c,
            t,
            [
                proposal(t.text, SemanticAction.CONSTRAINT, key="docs", value="sorted"),
                proposal(
                    t.text, SemanticAction.CONSTRAINT, key="date", value="2026-11-09"
                ),
            ],
        )
    assert e.snapshot().constraints == ()


def test_forget_and_late_proposal_cannot_resurrect():
    c = ConversationSession()
    e = SemanticContextEngine()
    apply(e, c, 1, "Nepal trip", SemanticAction.TOPIC, value="Nepal trip")
    apply(e, c, 5, "Forget Nepal trip", SemanticAction.FORGET_TOPIC)
    old = utterance(c, 3, "Nepal trip")
    with pytest.raises(SemanticRejected, match="stale asynchronous turn"):
        apply_epoch(
            e, c, old, [proposal(old.text, SemanticAction.TOPIC, value="Nepal trip")]
        )
    assert e.snapshot("Nepal trip") is None
    apply(e, c, 6, "Nepal trip", SemanticAction.TOPIC, value="Nepal trip")
    assert e.snapshot("Nepal trip") is not None
    e.clear()
    assert e.snapshot() is None


def test_reject_secret_and_unrelated_completion():
    c = ConversationSession()
    e = SemanticContextEngine()
    t = utterance(c, 1, "Remember my password")
    with pytest.raises(SemanticRejected, match="secret"):
        apply_epoch(
            e,
            c,
            t,
            [
                proposal(
                    t.text,
                    SemanticAction.TOPIC,
                    value="password",
                    sensitivity=Sensitivity.SECRET_PROHIBITED,
                )
            ],
        )
    apply(e, c, 2, "Nepal trip", SemanticAction.TOPIC, value="Nepal trip")
    apply(
        e,
        c,
        3,
        "Plan the route",
        SemanticAction.PENDING_STEP,
        key="route",
        value="route",
    )
    t = utterance(c, 4, "The documents are ready")
    with pytest.raises(SemanticRejected, match="name the pending step"):
        apply_epoch(
            e, c, t, [proposal(t.text, SemanticAction.COMPLETE_STEP, key="route")]
        )


def test_unknown_step_cannot_be_completed():
    c = ConversationSession()
    e = SemanticContextEngine()
    apply(e, c, 1, "Nepal trip", SemanticAction.TOPIC, value="Nepal trip")
    t = utterance(c, 2, "The route is complete")
    with pytest.raises(SemanticRejected, match="matching pending step"):
        apply_epoch(
            e, c, t, [proposal(t.text, SemanticAction.COMPLETE_STEP, key="route")]
        )


def test_duplicate_turn_replayed_only_once():
    c = ConversationSession()
    e = SemanticContextEngine()
    t = utterance(c, 1, "Nepal trip")
    p = proposal(t.text, SemanticAction.TOPIC, value="Nepal trip")
    assert apply_epoch(e, c, t, [p]) == 1
    assert apply_epoch(e, c, t, [p]) == 0


def test_hindi_and_hinglish_evidence_without_losing_source():
    c = ConversationSession()
    e = SemanticContextEngine()
    apply(e, c, 1, "नेपाल यात्रा", SemanticAction.TOPIC, value="नेपाल यात्रा")
    apply(
        e,
        c,
        2,
        "Budget ka issue nahi hai",
        SemanticAction.CONSTRAINT,
        key="budget",
        value="unrestricted",
    )
    state = dict(e.snapshot().constraints)["budget"]
    assert state.evidence == "Budget ka issue nahi hai"
    assert state.evidence_strength is EvidenceStrength.INTERPRETED


def test_hallucinated_topic_is_not_admitted():
    c = ConversationSession()
    e = SemanticContextEngine()
    t = utterance(c, 1, "Good morning")
    with pytest.raises(SemanticRejected, match="named"):
        apply_epoch(
            e, c, t, [proposal(t.text, SemanticAction.TOPIC, value="Nepal trip")]
        )


def test_stale_correction_cannot_override_newer_value():
    c = ConversationSession()
    e = SemanticContextEngine()
    apply(e, c, 1, "Nepal trip", SemanticAction.TOPIC, value="Nepal trip")
    apply(
        e,
        c,
        5,
        "Budget is unlimited",
        SemanticAction.CONSTRAINT,
        key="budget",
        value="unlimited",
    )
    t = utterance(c, 3, "Budget is tight")
    with pytest.raises(SemanticRejected, match="stale asynchronous turn"):
        apply_epoch(
            e,
            c,
            t,
            [proposal(t.text, SemanticAction.CORRECT, key="budget", value="tight")],
        )
    assert dict(e.snapshot().constraints)["budget"].value == "unlimited"


def test_revocation_epoch_blocks_inflight_proposal():
    c = ConversationSession()
    e = SemanticContextEngine()
    turn = utterance(c, 1, "Nepal trip")
    old_epoch = e.epoch
    e.clear()
    with pytest.raises(SemanticRejected, match="generation"):
        e.apply(
            c, turn,
            [proposal(turn.text, SemanticAction.TOPIC, value="Nepal trip")],
            epoch=old_epoch,
        )
    assert e.snapshot() is None


def test_late_topic_switch_cannot_change_active_topic():
    c = ConversationSession()
    e = SemanticContextEngine()
    apply(e, c, 10, "Nepal trip", SemanticAction.TOPIC, value="Nepal trip")
    old = utterance(c, 5, "Interview prep")
    with pytest.raises(SemanticRejected, match="stale asynchronous turn"):
        apply_epoch(
            e,
            c,
            old,
            [proposal(old.text, SemanticAction.TOPIC, value="Interview prep")],
        )
    assert e.active_topic == "Nepal trip"
