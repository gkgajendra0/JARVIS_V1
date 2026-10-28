import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import AcceptedLearningSource, LearningCatalog
from jarvis.memory.learning_extractors import LearningProviderAdapter
from jarvis.memory.learning_policy import LearningPolicy
from jarvis.memory.learning_reconciliation import LearningReconciler
from jarvis.memory.personal_context_projection import (
    parse_context_requests,
    project_personal_context,
)


def source(text):
    c = ConversationSession()
    c.start()
    t = c.accept_turn(ConversationRole.USER, text)
    return AcceptedLearningSource.from_turn("runtime", c, t, now=100)


async def extract(s, category, label, **fields):
    payload = {
        "candidates": [
            {
                "category": category,
                "intent": "new",
                "label": label,
                "value": s.text,
                "evidence": [{"turn_id": s.turn_id, "quote": s.text}],
                **fields,
            }
        ]
    }
    call = AsyncMock(return_value=SimpleNamespace(output_text=json.dumps(payload)))
    a = LearningProviderAdapter(
        "gemini",
        SimpleNamespace(aio=SimpleNamespace(interactions=SimpleNamespace(create=call))),
        "model",
    )
    batch = await a.extract(s)
    return a, batch, call


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category,text,label,fields",
    [
        (
            "personal_fact",
            "I work for Northstar Design Limited.",
            "Northstar Design Limited",
            {},
        ),
        (
            "activity",
            "Today I am working on my Jarvis project.",
            "Jarvis project",
            {"importance": "transient", "time_expression": "Today"},
        ),
        (
            "event",
            "Yesterday I visited Jaipur for a wedding.",
            "Jaipur",
            {
                "time_expression": "Yesterday",
                "location": "Jaipur",
                "reason": "a wedding",
                "state": "completed",
            },
        ),
        (
            "plan",
            "Tomorrow I might go to Pune for an interview.",
            "Pune",
            {
                "time_expression": "Tomorrow",
                "location": "Pune",
                "reason": "an interview",
                "state": "planned",
                "certainty": "tentative",
            },
        ),
    ],
)
async def test_personal_history_admission_and_recall(
    learning, category, text, label, fields
):
    s = source(text)
    a, batch, call = await extract(s, category, label, **fields)
    assert len(batch.candidates) == 1
    assert LearningPolicy().evaluate(s, batch.candidates[0]).status == "eligible"
    grant = learning.grant
    learning.authority.register_source(grant, s.receipt_id, source=s)
    reconciler = LearningReconciler(
        learning.service.canonical_reader, learning.authority
    )
    resolution = await a.resolve(s, batch, LearningCatalog())
    plan = reconciler.plan(s, batch, LearningCatalog(), resolution)
    result = await learning.service.admit_learning(
        plan, learning.authority.issue_child(grant, plan.binding())
    )
    assert result.status == "committed"
    snapshot = await learning.service.canonical_reader.learning_context_snapshot()
    projection = project_personal_context(
        snapshot,
        parse_context_requests(
            [{"scope_key": category}], question="What do you know about me?"
        ),
    )
    assert projection.status == "selected" and text in projection.facts[0]["text"]
    stored = snapshot.entries[0][0].value
    assert stored["temporal"]["recorded_at"]
    if "reason" in fields:
        assert stored["reason"] == fields["reason"]
        assert projection.facts[0]["reason"] == fields["reason"]
    if fields.get("time_expression", "").lower() in {"yesterday", "tomorrow"}:
        offset = -1 if category == "event" else 1
        expected = (
            s.turns[-1].accepted_at.astimezone().date() + timedelta(days=offset)
        ).isoformat()
        assert stored["temporal"]["date"] == expected
    if category == "plan":
        assert stored["certainty"] == "tentative"
    assert call.await_count == 1
    from context_query_helpers import context_session

    async with context_session(learning, question="What do you know about me?") as (
        personal,
        _,
        _,
    ):
        response = await personal.query_for_question([{"scope_key": category}])
        assert response["status"] == "selected"
        assert text in response["facts"][0]["text"]
        if "reason" in fields:
            assert response["facts"][0]["reason"] == fields["reason"]


@pytest.mark.asyncio
async def test_unsupported_metadata_is_rejected():
    s = source("I visited Jaipur.")
    _, batch, _ = await extract(s, "event", "Jaipur", reason="an interview")
    assert (
        LearningPolicy().evaluate(s, batch.candidates[0]).reason == "unsupported_reason"
    )


@pytest.mark.asyncio
async def test_unresolved_time_is_preserved_without_inventing_date():
    s = source("I plan to visit Pune sometime next month.")
    a, batch, _ = await extract(
        s, "plan", "Pune", time_expression="sometime next month", state="planned"
    )
    plan = LearningReconciler(None, None).plan(
        s, batch, LearningCatalog(), await a.resolve(s, batch, LearningCatalog())
    )
    temporal = plan.mutations[0].draft.value["temporal"]
    assert temporal["expression"] == "sometime next month" and temporal["date"] is None


@pytest.mark.asyncio
async def test_cancellation_keeps_original_plan_date_and_reason(learning):
    from jarvis.memory.learning_contracts import (
        LearningResolution,
        LearningResolutionBatch,
    )

    grant = learning.grant
    first = source("Tomorrow I plan to go to Pune for an interview.")
    a, batch, _ = await extract(
        first,
        "plan",
        "Pune",
        time_expression="Tomorrow",
        location="Pune",
        reason="an interview",
        state="planned",
    )
    learning.authority.register_source(grant, first.receipt_id, source=first)
    r = LearningReconciler(learning.service.canonical_reader, learning.authority)
    plan = r.plan(
        first,
        batch,
        LearningCatalog(),
        await a.resolve(first, batch, LearningCatalog()),
    )
    saved = await learning.service.admit_learning(
        plan, learning.authority.issue_child(grant, plan.binding())
    )
    old_date = plan.mutations[0].draft.value["temporal"]["date"]
    second = source("I cancelled my Pune trip.")
    _, batch, _ = await extract(
        second, "plan", "Pune", intent="change", state="cancelled"
    )
    learning.authority.register_source(grant, second.receipt_id, source=second)
    catalog = await r.catalog(second, batch, grant)
    resolutions = LearningResolutionBatch(
        resolutions=[
            LearningResolution(
                candidate_index=0, decision="match", target_id=saved.assertion_ids[0]
            )
        ]
    )
    update = r.plan(second, batch, catalog, resolutions)
    assert update.mutations[0].draft.value["temporal"]["date"] == old_date
    assert update.mutations[0].draft.value["reason"] == "an interview"
    result = await learning.service.admit_learning(
        update, learning.authority.issue_child(grant, update.binding())
    )
    snapshot = await learning.service.canonical_reader.learning_context_snapshot()
    projection = project_personal_context(
        snapshot,
        parse_context_requests(
            [{"scope_key": "plan"}], question="What about my plans?"
        ),
    )
    assert result.status == "committed" and projection.facts[0]["state"] == "cancelled"
    assert projection.facts[0]["temporal"]["date"] == old_date


@pytest.mark.asyncio
async def test_same_place_on_distinct_dates_is_not_collapsed(learning):
    from jarvis.memory.learning_contracts import (
        LearningResolution,
        LearningResolutionBatch,
    )

    grant = learning.grant
    r = LearningReconciler(learning.service.canonical_reader, learning.authority)
    for expression in ["Yesterday", "Today"]:
        s = source(expression + " I visited Jaipur.")
        _, batch, _ = await extract(
            s,
            "event",
            "Jaipur",
            value="Jaipur",
            time_expression=expression,
            state="completed",
        )
        learning.authority.register_source(grant, s.receipt_id, source=s)
        catalog = await r.catalog(s, batch, grant)
        resolutions = LearningResolutionBatch(
            resolutions=[LearningResolution(candidate_index=0, decision="new")]
        )
        plan = r.plan(s, batch, catalog, resolutions)
        assert len(plan.mutations) == 1
        result = await learning.service.admit_learning(
            plan, learning.authority.issue_child(grant, plan.binding())
        )
        assert result.status == "committed"
    snapshot = await learning.service.canonical_reader.learning_context_snapshot()
    dates = [record.value["temporal"]["date"] for record, scope in snapshot.entries]
    assert len(dates) == 2 and len(set(dates)) == 2


@pytest.mark.asyncio
async def test_date_phrase_uses_the_turn_that_supplied_it_across_midnight():
    from dataclasses import replace

    from jarvis.memory.learning_contracts import EvidenceSpan, LearningCandidate
    from jarvis.memory.learning_temporal import temporal_context

    s = source("Tomorrow I will visit Jaipur.")
    first = replace(s.turns[0], accepted_at=datetime(2026, 10, 20, 23, 59).astimezone())
    second = replace(
        first,
        turn_id="later",
        text="I will go for an interview.",
        accepted_at=first.accepted_at + timedelta(minutes=2),
    )
    s = replace(s, turns=(first, second))
    candidate = LearningCandidate(
        category="plan",
        intent="new",
        label="interview",
        value="an interview",
        time_expression="Tomorrow",
        state="planned",
        evidence=[
            EvidenceSpan(turn_id=first.turn_id, start=0, end=len(first.text)),
            EvidenceSpan(turn_id=second.turn_id, start=0, end=len(second.text)),
        ],
    )
    assert LearningPolicy().evaluate(s, candidate).status == "eligible"
    assert temporal_context(s, candidate)["date"] == "2026-10-21"


@pytest.mark.asyncio
async def test_long_valid_history_record_does_not_break_later_catalog(learning):
    value = "project " + "x" * 990
    reason = "a " + "r" * 490
    location = "L" * 220
    text = value + " at " + location + " because of " + reason
    s = source(text)
    a, batch, _ = await extract(
        s, "personal_fact", "project", value=value, reason=reason, location=location
    )
    grant = learning.grant
    learning.authority.register_source(grant, s.receipt_id, source=s)
    r = LearningReconciler(learning.service.canonical_reader, learning.authority)
    plan = r.plan(
        s, batch, LearningCatalog(), await a.resolve(s, batch, LearningCatalog())
    )
    await learning.service.admit_learning(
        plan, learning.authority.issue_child(grant, plan.binding())
    )
    catalog = await r.catalog(s, batch, grant)
    assert len(catalog.entries) == 1 and len(catalog.entries[0].value) > 1800


@pytest.mark.asyncio
async def test_changed_employer_can_be_recalled_by_new_name(learning):
    from jarvis.memory.learning_contracts import (
        LearningResolution,
        LearningResolutionBatch,
    )

    grant = learning.grant
    first = source("I work for Northstar Design Limited.")
    a, batch, _ = await extract(first, "personal_fact", "Northstar Design Limited")
    learning.authority.register_source(grant, first.receipt_id, source=first)
    r = LearningReconciler(learning.service.canonical_reader, learning.authority)
    plan = r.plan(
        first,
        batch,
        LearningCatalog(),
        await a.resolve(first, batch, LearningCatalog()),
    )
    saved = await learning.service.admit_learning(
        plan, learning.authority.issue_child(grant, plan.binding())
    )
    second = source("Now I work for Contoso.")
    _, batch, _ = await extract(second, "personal_fact", "Contoso", intent="change")
    learning.authority.register_source(grant, second.receipt_id, source=second)
    catalog = await r.catalog(second, batch, grant)
    update = r.plan(
        second,
        batch,
        catalog,
        LearningResolutionBatch(
            resolutions=[
                LearningResolution(
                    candidate_index=0,
                    decision="match",
                    target_id=saved.assertion_ids[0],
                )
            ]
        ),
    )
    await learning.service.admit_learning(
        update, learning.authority.issue_child(grant, update.binding())
    )
    snapshot = await learning.service.canonical_reader.learning_context_snapshot()
    projection = project_personal_context(
        snapshot,
        parse_context_requests(
            [{"scope_key": "personal_fact", "target_quote": "Contoso"}],
            question="What about Contoso?",
        ),
    )
    assert (
        projection.status == "selected"
        and "Now I work for Contoso." in projection.facts[0]["text"]
    )
