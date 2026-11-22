"""Run 5 (lab 7a0a29e2) D12 and D16, reproduced from the recorded outputs.

D12: "I misspoke, the Jimny is from September, not October." was proposed as
a correction with label "Jimny" but value "September" (the month in the value
field). The correction rebuilt the whole stored value from the proposal, so
the Jimny's value became "September". Fix: a correction of an owned item
replaces only what it restates; the item's identity and unrelated attributes
are kept, and an owned item's value is never one of its own times.

D16: "How do you know I have a Jimny, and when did I tell you?" was answered
"You mentioned it in September (specifically, recorded on November 22,
2026)": the answer model had no quote and no told date for owned items, only
recorded_at (the system's recording time). Fix: each released fact carries
told.how / told.date / told.quote from its own source and first_told from the
earliest owner telling in the item's lineage; an unknown date stays null.
"""

from __future__ import annotations

import json
from dataclasses import replace as dc_replace
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import (
    AcceptedLearningSource,
    EvidenceSpan,
    LearningBatch,
    LearningCandidate,
    LearningCatalog,
    LearningCatalogEntry,
    LearningResolutionBatch,
)
from jarvis.memory.learning_policy import LearningPolicy
from jarvis.memory.learning_reconciliation import LearningReconciler
from jarvis.memory.personal_context_projection import _learned

IST = ZoneInfo("Asia/Kolkata")
RUN5 = json.loads(
    (Path(__file__).parent / "fixtures" / "run5_d12_recorded.json").read_text(
        encoding="utf-8"
    )
)
JIMNY_ID = RUN5["steps"]["story-12"]["resolution"]["resolutions"][0]["target_id"]


class StampedConversation(ConversationSession):
    """Turns stamped with the case's told time (midday IST, so the local and
    UTC dates agree)."""

    def say(self, text, day):
        turn = self.accept_turn(ConversationRole.USER, text)
        at = datetime.fromisoformat(f"{day}T12:00:00").replace(tzinfo=IST)
        stamped = dc_replace(turn, accepted_at=at.astimezone(UTC))
        self._turns[-1] = stamped
        return stamped


def _source(text, day="2026-11-19"):
    c = StampedConversation()
    c.start()
    turn = c.say(text, day)
    return AcceptedLearningSource.from_turn("runtime", c, turn, now=100)


def _recorded(step, index=0, text=None, day=None, **changes):
    """A recorded run-5 proposal. Only the evidence turn id is rebound to the
    replay turn; ``changes`` exist only for the negative cases."""
    source = _source(text or RUN5["owner_said"][step], day or RUN5["told_at"][step])
    raw = json.loads(json.dumps(RUN5["steps"][step]["extraction"]["candidates"][index]))
    raw.update(changes)
    if text and "evidence" not in changes:
        raw["evidence"] = [{"turn_id": "x", "start": 0, "end": len(text)}]
    for span in raw["evidence"]:
        span["turn_id"] = source.turn_id
    return source, LearningCandidate.model_validate(raw)


def _entry(value, assertion_id, predicate=None):
    return LearningCatalogEntry(
        assertion_id=assertion_id,
        predicate=predicate or f"owned_item_{assertion_id}",
        category="owned_item",
        text=f"owned_item.vehicle: {value['label']}",
        value=json.dumps(value, ensure_ascii=False),
        kind="vehicle",
    )


def _stored_story_02():
    """The three D1 items, created from the recorded story-02 proposals."""
    source, _ = _recorded("story-02")
    candidates = [
        _recorded("story-02", i)[1].model_copy(
            update={
                "evidence": [
                    EvidenceSpan(turn_id=source.turn_id, start=0, end=len(source.text))
                ]
            }
        )
        for i in range(3)
    ]
    plan = LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=candidates),
        LearningCatalog(),
        LearningResolutionBatch.model_validate(RUN5["steps"]["story-02"]["resolution"]),
    )
    values = {m.draft.value["label"]: m.draft.value for m in plan.mutations}
    ids = {
        "Royal Enfield Classic 350": "classic",
        "Tata Tigor": "tigor",
        "Jimny": JIMNY_ID,
    }
    return {label: _entry(v, ids[label]) for label, v in values.items()}


def _correct(entries, target_id, source, candidate):
    return LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(entries=list(entries)),
        LearningResolutionBatch(
            resolutions=[
                {"candidate_index": 0, "decision": "match", "target_id": target_id}
            ]
        ),
    )


# -- D12 -----------------------------------------------------------------------


def test_run5_d12_recorded_proposal_put_the_month_in_value():
    _, candidate = _recorded("story-12")
    assert (candidate.label, candidate.value) == ("Jimny", "September")
    assert candidate.intent == "correction"


def test_run5_d12_correction_keeps_the_jimny_and_corrects_only_the_month():
    entries = _stored_story_02()
    jimny_before = json.loads(entries["Jimny"].value)
    assert jimny_before["value"] == "Jimny"
    assert jimny_before["acquired"]["earliest"] == "2026-10-01"  # "last month"
    source, candidate = _recorded("story-12")
    assert LearningPolicy().evaluate(source, candidate).status == "eligible"
    plan = _correct(entries.values(), JIMNY_ID, source, candidate)
    (mutation,) = plan.mutations
    assert mutation.action == "correct"
    assert mutation.expected_assertion_id == JIMNY_ID
    value = mutation.draft.value
    assert (value["label"], value["value"]) == ("Jimny", "Jimny")  # run 5: September
    assert value["acquired"] == {
        **value["acquired"],
        "expression": "September",
        "precision": "month",
        "earliest": "2026-09-01",
        "latest": "2026-09-30",
        "basis": "inferred_year",
    }
    unchanged = {k: v for k, v in jimny_before.items() if k != "acquired"}
    assert {k: value[k] for k in unchanged} == unchanged
    assert "value=September" not in mutation.draft.normalized_text


def test_correction_keeps_unrelated_details_and_aliases():
    entries = _stored_story_02()
    jimny = json.loads(entries["Jimny"].value)
    jimny.update(details="the white one", aliases=["the 4x4"])
    entries["Jimny"] = _entry(jimny, JIMNY_ID)
    source, candidate = _recorded("story-12")
    (mutation,) = _correct(entries.values(), JIMNY_ID, source, candidate).mutations
    value = mutation.draft.value
    assert value["details"] == "the white one" and value["aliases"] == ["the 4x4"]
    assert value["acquired"]["earliest"] == "2026-09-01"


def test_the_same_protection_applies_to_other_owned_items():
    entries = _stored_story_02()
    text = "Sorry, the Tigor is from April 2017, not March."
    source, candidate = _recorded(
        "story-12",
        text=text,
        label="Tigor",
        value="April 2017",
        time_expression="April 2017",
        acquired_expression="April 2017",
    )
    assert LearningPolicy().evaluate(source, candidate).status == "eligible"
    (mutation,) = _correct(entries.values(), "tigor", source, candidate).mutations
    value = mutation.draft.value
    assert (value["label"], value["value"]) == ("Tata Tigor", "Tata Tigor")
    assert (value["acquired"]["earliest"], value["acquired"]["latest"]) == (
        "2017-04-01",
        "2017-04-30",
    )


def test_a_corrected_name_corrects_the_identity_and_keeps_the_dates():
    entries = _stored_story_02()
    text = "I misspoke, it's a Gypsy, not a Jimny."
    source, candidate = _recorded(
        "story-12",
        text=text,
        label="Gypsy",
        value="Gypsy",
        time_expression=None,
        acquired_expression=None,
    )
    (mutation,) = _correct(entries.values(), JIMNY_ID, source, candidate).mutations
    value = mutation.draft.value
    assert (value["label"], value["value"]) == ("Gypsy", "Gypsy")
    assert value["acquired"] == json.loads(entries["Jimny"].value)["acquired"]


def test_a_detail_correction_keeps_the_purchase_time():
    entries = _stored_story_02()
    text = "Correction: the Jimny is the petrol one."
    source, candidate = _recorded(
        "story-12",
        text=text,
        value="Jimny",
        details="the petrol one",
        time_expression=None,
        acquired_expression=None,
    )
    (mutation,) = _correct(entries.values(), JIMNY_ID, source, candidate).mutations
    value = mutation.draft.value
    assert value["details"] == "the petrol one" and value["value"] == "Jimny"
    assert value["acquired"] == json.loads(entries["Jimny"].value)["acquired"]


def test_a_state_corrected_back_to_owned_drops_the_disposal_time():
    entries = _stored_story_02()
    tigor = json.loads(entries["Tata Tigor"].value)
    tigor.update(
        state="sold",
        disposed={
            "expression": "last week",
            "precision": "week",
            "earliest": "2026-11-09",
            "latest": "2026-11-15",
            "basis": "stated",
        },
    )
    entries["Tata Tigor"] = _entry(tigor, "tigor")
    text = "Actually I never sold the Tigor, I still have it."
    source, candidate = _recorded(
        "story-12",
        text=text,
        label="Tigor",
        value="Tigor",
        state="owned",
        time_expression=None,
        acquired_expression=None,
    )
    (mutation,) = _correct(entries.values(), "tigor", source, candidate).mutations
    value = mutation.draft.value
    assert value["state"] == "owned" and "disposed" not in value
    assert value["value"] == "Tata Tigor" and value["acquired"] == tigor["acquired"]


def test_a_new_item_never_stores_its_time_as_its_value():
    text = "I bought a Duster in March 2024."
    source, candidate = _recorded(
        "story-12",
        text=text,
        intent="new",
        label="Duster",
        value="March 2024",
        time_expression="March 2024",
        acquired_expression="March 2024",
    )
    plan = LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(),
        LearningResolutionBatch(
            resolutions=[{"candidate_index": 0, "decision": "new"}]
        ),
    )
    (mutation,) = plan.mutations
    assert mutation.draft.value["value"] == "Duster"
    assert mutation.draft.value["acquired"]["earliest"] == "2024-03-01"


def test_a_value_that_differs_from_the_label_is_kept_when_it_is_not_a_time():
    _, candidate = _recorded("story-02", 0)
    text = "I have a Classic 350, a Royal Enfield Classic 350 from 2021."
    source, candidate = _recorded(
        "story-02", 0, text=text, label="Classic 350", day="2026-11-17"
    )
    plan = LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(),
        LearningResolutionBatch(
            resolutions=[{"candidate_index": 0, "decision": "new"}]
        ),
    )
    assert plan.mutations[0].draft.value["value"] == "Royal Enfield Classic 350"


# -- D16: what the answer model is told about how a fact was learned -------------

OWNER = "owner_direct"


def test_told_date_quote_and_how_from_the_fact_s_own_source():
    learned = _learned(
        ((OWNER, "2026-11-19T06:30:00Z", "the Jimny is from September"),)
    )
    assert learned == {
        "told": {
            "how": "owner_said",
            "date": "2026-11-19",
            "quote": "the Jimny is from September",
        }
    }


def test_correction_lineage_reports_the_first_telling_separately():
    learned = _learned(
        (
            (OWNER, "2026-11-19T06:30:00Z", "the Jimny is from September"),
            (OWNER, "2026-11-17T06:30:00Z", "last month I got a Jimny"),
        )
    )
    assert learned["told"]["date"] == "2026-11-19"
    assert learned["first_told"] == {
        "how": "owner_said",
        "date": "2026-11-17",
        "quote": "last month I got a Jimny",
    }


def test_the_earliest_of_several_earlier_tellings_is_first_told():
    learned = _learned(
        (
            (OWNER, "2026-11-20T06:30:00Z", "c"),
            (OWNER, "2026-11-18T06:30:00Z", "b"),
            ("owner_explicit", "2026-11-01T06:30:00Z", None),
        )
    )
    assert learned["first_told"] == {
        "how": "owner_asked_to_remember",
        "date": "2026-11-01",
    }


def test_an_unknown_told_time_is_null_never_invented():
    for observed in (None, "", "not a time", "2026-11-19T06:30:00"):
        learned = _learned(((OWNER, observed, "q"),))
        assert learned["told"]["date"] is None
        assert "first_told" not in learned
    assert _learned(()) == {"told": {"how": "unknown", "date": None}}


def test_a_non_owner_source_has_no_told_date_or_quote():
    learned = _learned((("external_file", "2026-11-19T06:30:00Z", "x"),))
    assert learned == {"told": {"how": "external_file", "date": None}}


def test_no_first_told_for_the_same_telling():
    same = (OWNER, "2026-11-19T06:30:00Z", "q")
    assert "first_told" not in _learned((same, same))
    # An earlier row without a readable date adds nothing.
    assert "first_told" not in _learned((same, (OWNER, None, "older")))


# -- On a real (fictional) database: correction lineage reaches the release -----


@pytest.mark.asyncio
async def test_released_jimny_carries_told_dates_quotes_and_recorded_at(learning):
    from test_slice1_pr_b import Owner, item

    from jarvis.memory.personal_context_projection import (
        parse_context_requests,
        project_personal_context,
    )
    from jarvis.memory.retrieval import SemanticRetrievalService

    owner = Owner(learning)
    d1 = RUN5["owner_said"]["story-02"]
    await owner.say(
        d1,
        [item("Jimny", ["last month I got a Jimny"], acquired_expression="last month")],
        [("new", None)],
    )
    d12 = RUN5["owner_said"]["story-12"]
    _plan, result, _turn = await owner.say(
        d12,
        [
            item(
                "Jimny",
                ["the Jimny is from September"],
                intent="correction",
                value="September",
                time_expression="September",
                acquired_expression="September",
            )
        ],
        [("match", "Jimny")],
    )
    assert result.status == "committed"
    snapshot = await SemanticRetrievalService(
        learning.reader
    ).learning_context_snapshot(("owned_item.vehicle",))
    projection = project_personal_context(
        snapshot,
        parse_context_requests(
            [{"scope_key": "owned_item.vehicle"}],
            question="How do you know I have a Jimny, and when did I tell you?",
        ),
    )
    (fact,) = projection.facts
    assert "value=Jimny" in fact["text"] and "value=September" not in fact["text"]
    assert fact["told"]["how"] == "owner_said"
    assert fact["told"]["quote"] == "the Jimny is from September"
    assert fact["told"]["date"] is not None
    assert fact["first_told"]["quote"] == "last month I got a Jimny"
    assert fact["acquired"]["expression"] == "September"
    assert "recorded_at" in fact  # still present, and separate from told
