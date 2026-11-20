"""Slice 1 through real learning admission (authority, receipts, storage):
a learned real-world change no longer writes the time Jarvis was told as the
event time, ends current ownership, and a refine mutation keeps the earlier
true row unretracted."""

from dataclasses import replace

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import (
    AcceptedLearningSource,
    EvidenceSpan,
    LearningBatch,
    LearningCandidate,
    LearningCatalog,
    LearningCatalogEntry,
    LearningResolution,
    LearningResolutionBatch,
)
from jarvis.memory.learning_reconciliation import LearningReconciler


async def admit_first(learning):
    result = await learning.service.admit_learning(learning.plan, learning.new_permit())
    assert result.status == "committed"
    return result.assertion_ids[0]


async def catalog(learning):
    records = await learning.service.canonical_reader.learning_current()
    entries = []
    import json

    for record in records:
        entries.append(
            LearningCatalogEntry(
                assertion_id=record.assertion_id,
                predicate=record.predicate,
                category="owned_item",
                kind="vehicle",
                text=record.normalized_text,
                value=json.dumps(record.value),
            )
        )
    return LearningCatalog(entries=entries)


def later_source(learning, text):
    conversation = ConversationSession()
    conversation.start()
    turn = conversation.accept_turn(ConversationRole.USER, text)
    source = AcceptedLearningSource.from_turn("runtime", conversation, turn, now=200)
    learning.authority.register_source(learning.grant, source.receipt_id, source=source)
    return source, turn


async def rows(learning):
    return await learning.reader.run(
        lambda c: c.execute(
            "SELECT assertion_id,state,valid_from,valid_to,system_to"
            " FROM semantic_assertion ORDER BY system_from, assertion_id"
        ).fetchall()
    )


@pytest.mark.asyncio
async def test_learned_sale_ends_current_ownership_with_unknown_effective_time(
    learning,
):
    owned_id = await admit_first(learning)
    source, turn = later_source(learning, "I sold the City last week")
    candidate = LearningCandidate(
        category="owned_item",
        kind="vehicle",
        intent="change",
        label="City",
        value="City",
        state="not_owned",
        time_expression="last week",
        evidence=[EvidenceSpan(turn_id=turn.turn_id, start=0, end=25)],
    )
    plan = LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        await catalog(learning),
        LearningResolutionBatch(
            resolutions=[
                LearningResolution(
                    candidate_index=0, decision="match", target_id=owned_id
                )
            ]
        ),
    )
    assert [m.action for m in plan.mutations] == ["change"]
    assert plan.mutations[0].effective_at is None
    result = await learning.service.admit_learning(
        plan, learning.authority.issue_child(learning.grant, plan.binding())
    )
    assert result.status == "committed"
    stored = await rows(learning)
    old = next(r for r in stored if r[0] == owned_id)
    new = next(r for r in stored if r[0] == result.assertion_ids[0])
    assert old[1] == "superseded" and old[3] is None and old[4] is not None
    assert new[1] == "active" and new[2] is None
    current = await learning.service.canonical_reader.learning_current()
    assert [r.assertion_id for r in current] == [new[0]]
    assert current[0].value["state"] == "not_owned"
    # When Jarvis was told stays on the source, separate from the event time.
    observed = await learning.reader.run(
        lambda c: c.execute(
            "SELECT s.observed_at FROM semantic_assertion a JOIN memory_source s"
            " ON s.source_id=a.source_id WHERE a.assertion_id=?",
            (new[0],),
        ).fetchone()[0]
    )
    assert observed.startswith(turn.accepted_at.astimezone().date().isoformat()[:4])


@pytest.mark.asyncio
async def test_refine_mutation_through_admission_keeps_the_earlier_row_true(learning):
    owned_id = await admit_first(learning)
    source, turn = later_source(learning, "The City is the diesel one")
    candidate = LearningCandidate(
        category="owned_item",
        kind="vehicle",
        intent="change",
        label="City",
        value="City",
        state="owned",
        evidence=[EvidenceSpan(turn_id=turn.turn_id, start=0, end=26)],
    )
    plan = LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        await catalog(learning),
        LearningResolutionBatch(
            resolutions=[
                LearningResolution(
                    candidate_index=0, decision="match", target_id=owned_id
                )
            ]
        ),
    )
    # PR A provides the storage operation; PR B's reconciler chooses it.
    refine_plan = replace(
        plan,
        mutations=(
            replace(
                plan.mutations[0],
                action="refine",
                draft=replace(
                    plan.mutations[0].draft,
                    value={**plan.mutations[0].draft.value, "details": "diesel"},
                ),
            ),
        ),
    )
    result = await learning.service.admit_learning(
        refine_plan,
        learning.authority.issue_child(learning.grant, refine_plan.binding()),
    )
    assert result.status == "committed"
    stored = await rows(learning)
    old = next(r for r in stored if r[0] == owned_id)
    assert old[1] == "superseded" and old[1] != "retracted"
    assert old[2] is None and old[3] is None
    ops = await learning.reader.run(
        lambda c: c.execute(
            "SELECT operation_type FROM memory_operation WHERE target_id=?",
            (result.assertion_ids[0],),
        ).fetchall()
    )
    assert ops == [("refine",)]
    current = await learning.service.canonical_reader.learning_current()
    assert [r.value.get("details") for r in current] == ["diesel"]


def test_plan_time_is_stored_with_precision_but_release_fields_are_unchanged():
    """PR A stores precision and bounds; the release keeps its existing fields
    and size until the paged budget lands (PR C)."""
    from test_context_projection import NOW, record

    from jarvis.memory.personal_context_projection import (
        ScopedContextSnapshot,
        parse_context_requests,
        project_personal_context,
    )

    conversation = ConversationSession()
    conversation.start()
    turn = conversation.accept_turn(
        ConversationRole.USER, "Last month I planned the Rishikesh trip"
    )
    source = AcceptedLearningSource.from_turn("runtime", conversation, turn, now=1)
    candidate = LearningCandidate(
        category="plan",
        intent="new",
        label="Rishikesh trip",
        value="Rishikesh trip",
        state="planned",
        time_expression="Last month",
        evidence=[EvidenceSpan(turn_id=turn.turn_id, start=0, end=39)],
    )
    plan = LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(),
        LearningResolutionBatch(
            resolutions=[LearningResolution(candidate_index=0, decision="new")]
        ),
    )
    temporal = plan.mutations[0].draft.value["temporal"]
    assert temporal["expression"] == "Last month"
    assert temporal["precision"] == "month"
    assert temporal["earliest"].endswith("-01") and temporal["date"] is None
    assert plan.mutations[0].draft.valid_from is None

    stored = record(
        "Rishikesh trip",
        "p",
        predicate="plan_p",
        value=plan.mutations[0].draft.value,
        system_from=NOW,
    )
    released = project_personal_context(
        ScopedContextSnapshot(((stored, "plan"),), ()),
        parse_context_requests([{"scope_key": "plan"}], question="my plans?"),
    )
    assert released.status == "selected"
    assert set(released.facts[0]["temporal"]) == {
        "expression",
        "date",
        "recorded_at",
        "anchor_at",
        "local_date",
    }


def test_plan_saved_before_new_date_rules_still_matches_the_same_day():
    """A plan stored when '14 March 2027' did not resolve (date None) is the
    same occurrence as the same plan mentioned again now."""
    import json

    from jarvis.memory.learning_temporal import occurrence_matches

    conversation = ConversationSession()
    conversation.start()
    turn = conversation.accept_turn(
        ConversationRole.USER, "The Pune interview is on 14 March 2027"
    )
    source = AcceptedLearningSource.from_turn("runtime", conversation, turn, now=1)
    candidate = LearningCandidate(
        category="plan",
        intent="new",
        label="Pune interview",
        value="Pune interview",
        state="planned",
        time_expression="14 March 2027",
        evidence=[EvidenceSpan(turn_id=turn.turn_id, start=0, end=38)],
    )
    anchor = turn.accepted_at.astimezone().isoformat()
    legacy = LearningCatalogEntry(
        assertion_id="old",
        predicate="plan_old",
        category="plan",
        text="plan",
        value=json.dumps(
            {
                "label": "Pune interview",
                "temporal": {
                    "expression": "14 March 2027",
                    "date": None,
                    "anchor_at": anchor,
                    "local_date": "2026-01-01",
                },
            }
        ),
    )
    assert occurrence_matches(legacy, candidate, source)
    other_day = legacy.model_copy(
        update={
            "value": legacy.value.replace("14 March 2027", "15 March 2027"),
        }
    )
    assert not occurrence_matches(other_day, candidate, source)
