from uuid import uuid4

import pytest
from pydantic import ValidationError

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import (
    AcceptedLearningSource,
    EvidenceSpan,
    LearningBatch,
    LearningCandidate,
)
from jarvis.memory.learning_policy import LearningPolicy


def source(text, previous=None):
    conversation = ConversationSession()
    conversation.start()
    if previous:
        conversation.accept_turn(ConversationRole.USER, previous)
    turn = conversation.accept_turn(ConversationRole.USER, text)
    return AcceptedLearningSource.from_turn("runtime", conversation, turn, now=100)


def candidate(s, value, **changes):
    start = s.text.index(value)
    return LearningCandidate(
        category="owned_item",
        kind="vehicle",
        intent="new",
        label=value,
        value=value,
        evidence=[EvidenceSpan(turn_id=s.turn_id, start=start, end=start + len(value))],
        **changes,
    )


@pytest.mark.parametrize(
    "text,value",
    [
        ("I own a City", "City"),
        ("मेरे पास सिटी है", "सिटी"),
        ("Mere paas City hai", "City"),
    ],
)
def test_exact_original_script_spans_are_supported(text, value):
    s = source(text)
    assert (
        LearningPolicy().evaluate(s, candidate(s, value), frozenset()).status
        == "eligible"
    )


def test_invented_value_is_rejected():
    s = source("Mere paas City hai")
    c = candidate(s, "City").model_copy(update={"value": "Creta"})
    assert LearningPolicy().evaluate(s, c, frozenset()).status == "drop"


@pytest.mark.parametrize(
    "field,value",
    [
        ("qualification", "quoted"),
        ("qualification", "hypothetical"),
        ("qualification", "uncertain"),
        ("sensitivity", "private"),
        ("sensitivity", "local_only"),
        ("sensitivity", "secret_prohibited"),
    ],
)
def test_non_direct_or_sensitive_proposals_never_admit(field, value):
    s = source("I own a City")
    c = candidate(s, "City").model_copy(update={field: value})
    assert LearningPolicy().evaluate(s, c, frozenset()).status == "drop"


def test_transient_and_suppressed_facts_are_not_permanent():
    s = source("I own a City")
    c = candidate(s, "City")
    assert (
        LearningPolicy()
        .evaluate(s, c.model_copy(update={"importance": "transient"}), frozenset())
        .status
        == "transient"
    )
    assert (
        LearningPolicy().evaluate(s, c, frozenset({"owned_item.vehicle"})).status
        == "drop"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Don't remember this: I own a City",
        "City hai, yaad mat rakhna",
        "मेरे पास सिटी है, याद मत रखना",
    ],
)
def test_memory_veto_drops_before_provider(text):
    s = source(text)
    assert LearningPolicy.source_allowed(s) is False


def test_old_turn_alone_cannot_admit_new_truth():
    s = source("Okay", "I own a City")
    old = s.turns[0]
    c = LearningCandidate(
        category="owned_item",
        kind="vehicle",
        intent="new",
        label="City",
        value="City",
        evidence=[EvidenceSpan(turn_id=old.turn_id, start=8, end=12)],
    )
    assert LearningPolicy().evaluate(s, c, frozenset()).status == "drop"


def test_source_and_batch_are_bounded():
    with pytest.raises(ValueError):
        source("a" * 8001)
    s = source("I own a City")
    with pytest.raises(ValidationError):
        LearningBatch(candidates=[candidate(s, "City")] * 9)
    with pytest.raises(ValidationError):
        candidate(s, "City", permit_id=str(uuid4()))


def test_noncanonical_or_assistant_turn_cannot_be_source():
    c = ConversationSession()
    c.start()
    t = c.accept_turn(ConversationRole.ASSISTANT, "I own a City")
    with pytest.raises(ValueError):
        AcceptedLearningSource.from_turn("runtime", c, t, now=100)
