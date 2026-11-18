"""Learning and answering the same owner turn (voice-eval-1, 2026-11-18).

Owner: "I am going to Gokarna from Bengaluru for a long weekend next month.
Help me decide how to get there." Jarvis looked up the vehicle and plan
scopes (plan was empty), released the vehicle fact and answered with it. 12.7 s
after the question, automatic learning committed the Gokarna plan FROM THAT
SAME TURN into the looked-up plan scope. The release signature covers every
looked-up scope, so the answer was treated as stale: audio cleared, personal
session retired as "invalidated", voice session ended.

A fact learned from the very words being answered adds nothing the answer did
not already have. Only that case is accepted: the released facts unchanged, no
looked-up row replaced or removed, suppression unchanged, and every added row
sourced from the bound turn. Anything else still ends the answer.
"""

from types import SimpleNamespace

import pytest
from test_personal_context_session import _question, _setup

from jarvis.conversation import ConversationRole
from jarvis.memory.learning_contracts import (
    AcceptedLearningSource,
    EvidenceSpan,
    LearningBatch,
    LearningCandidate,
    LearningCatalog,
    LearningResolution,
    LearningResolutionBatch,
)
from jarvis.memory.learning_reconciliation import LearningReconciler

QUESTION = (
    "I am going to Gokarna from Bengaluru for a long weekend next month. "
    "Help me decide how to get there."
)
VEHICLE_AND_PLAN = [{"scope_key": "owned_item.vehicle"}, {"scope_key": "plan"}]


@pytest.fixture(autouse=True)
def proposal_clock(monkeypatch, clock):
    from jarvis.authority import proposal

    monkeypatch.setattr(proposal, "time", SimpleNamespace(monotonic=clock))


def plan_fact(turn, text="Gokarna"):
    start = turn.text.index(text)
    return LearningCandidate(
        category="plan",
        intent="new",
        label=text,
        value=text,
        state="planned",
        evidence=[
            EvidenceSpan(turn_id=turn.turn_id, start=start, end=start + len(text))
        ],
    )


def accepted_source(learning, conversation, turn):
    """Created when ``turn`` is accepted, as the learning worker does."""
    source = AcceptedLearningSource.from_turn("runtime", conversation, turn, now=100)
    learning.authority.register_source(learning.grant, source.receipt_id, source=source)
    return source


async def learn(learning, conversation, turn, candidate, *, source=None):
    """The production admission path for a new fact from ``turn``."""
    source = source or accepted_source(learning, conversation, turn)
    plan = LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(),
        LearningResolutionBatch(
            resolutions=[LearningResolution(candidate_index=0, decision="new")]
        ),
    )
    result = await learning.service.admit_learning(
        plan, learning.authority.issue_child(learning.grant, plan.binding())
    )
    assert result.status == "committed"


async def answered(learning, authority_parts, text=QUESTION):
    factory, session = await _setup(learning, authority_parts)  # City saved
    conversation = _question(text)
    personal = factory(conversation)
    result = await personal.query_for_question(VEHICLE_AND_PLAN)
    assert result["status"] == "selected"
    inner = personal._inner
    assert await inner._facts_current()
    return personal, inner, session, conversation


@pytest.mark.asyncio
async def test_a_plan_learned_from_the_question_being_answered_keeps_the_answer(
    learning, authority_parts
):
    personal, inner, session, conversation = await answered(learning, authority_parts)
    try:
        turn = conversation.turns[-1]
        await learn(learning, conversation, turn, plan_fact(turn))
        assert await inner._facts_current()
        assert await inner.allow_audio()
        assert inner.retirement_reason is None
    finally:
        personal.close()
        session.close()


@pytest.mark.asyncio
async def test_a_fact_learned_from_another_conversation_still_ends_the_answer(
    learning, authority_parts
):
    personal, inner, session, _ = await answered(learning, authority_parts)
    try:
        elsewhere = _question("I am planning a trip to Hampi next month.")
        turn = elsewhere.turns[-1]
        await learn(learning, elsewhere, turn, plan_fact(turn, "Hampi"))
        assert not await inner._facts_current()
    finally:
        personal.close()
        session.close()


@pytest.mark.asyncio
async def test_a_fact_from_an_earlier_turn_of_the_same_conversation_still_ends_it(
    learning, authority_parts
):
    """Kept strict: only the bound turn's own words are known to the answer."""
    factory, session = await _setup(learning, authority_parts)
    conversation = _question("I am planning a trip to Hampi next month.")
    earlier = conversation.turns[-1]
    queued = accepted_source(learning, conversation, earlier)  # still in the queue
    conversation.accept_turn(ConversationRole.USER, QUESTION)
    personal = factory(conversation)
    try:
        assert (await personal.query_for_question(VEHICLE_AND_PLAN))["status"] == (
            "selected"
        )
        await learn(
            learning, conversation, earlier, plan_fact(earlier, "Hampi"), source=queued
        )
        assert not await personal._inner._facts_current()
    finally:
        personal.close()
        session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["corrected", "forgotten", "category_disabled"])
async def test_changes_to_looked_up_facts_still_end_the_answer_after_a_same_turn_fact(
    learning, authority_parts, change
):
    personal, inner, session, conversation = await answered(learning, authority_parts)
    statements = {
        "corrected": "UPDATE semantic_assertion SET normalized_text='Nexon' "
        "WHERE predicate LIKE 'owned_item_%'",
        "forgotten": "UPDATE semantic_assertion SET state='retracted' "
        "WHERE predicate LIKE 'owned_item_%'",
        "category_disabled": "INSERT INTO personal_learning_suppression "
        "VALUES ('plan',1,1,'fictional')",
    }

    def update(connection):
        with connection:
            connection.execute(statements[change])

    try:
        turn = conversation.turns[-1]
        await learn(learning, conversation, turn, plan_fact(turn))
        assert await inner._facts_current()
        await learning.writer.run(update)
        assert not await inner._facts_current()
    finally:
        personal.close()
        session.close()


@pytest.mark.asyncio
async def test_a_same_turn_change_to_the_released_fact_still_ends_the_answer(
    learning, authority_parts
):
    """The answer used the City; the same words say it was sold: stale, as before."""
    text = "I sold the City last week. How should I get to Gokarna?"
    personal, inner, session, conversation = await answered(
        learning, authority_parts, text
    )
    try:
        turn = conversation.turns[-1]
        start = turn.text.index("City")
        candidate = LearningCandidate(
            category="owned_item",
            kind="vehicle",
            intent="change",
            label="City",
            value="City",
            state="not_owned",
            evidence=[EvidenceSpan(turn_id=turn.turn_id, start=start, end=start + 4)],
        )
        source = accepted_source(learning, conversation, turn)
        batch = LearningBatch(candidates=[candidate])
        reconciler = LearningReconciler(
            learning.service.canonical_reader, learning.authority
        )
        catalog = await reconciler.catalog(source, batch, learning.grant)
        (city,) = [e for e in catalog.entries if e.kind == "vehicle"]
        plan = reconciler.plan(
            source,
            batch,
            catalog,
            LearningResolutionBatch(
                resolutions=[
                    LearningResolution(
                        candidate_index=0, decision="match", target_id=city.assertion_id
                    )
                ]
            ),
        )
        result = await learning.service.admit_learning(
            plan, learning.authority.issue_child(learning.grant, plan.binding())
        )
        assert result.status == "committed"
        assert not await inner._facts_current()
    finally:
        personal.close()
        session.close()
