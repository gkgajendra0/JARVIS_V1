"""Lab 7 (lab 5284bc26) D12, D23 and D15, reproduced from the recorded outputs.

Shared cause for D12 and D23: reconciliation trusted which field or intent
the model used, and nothing checked the resulting record.
- D12: the correction put the month in ``details`` and ``time_expression``
  (no ``acquired_expression``), so the item kept October and gained
  details "September".
- D23: "I sold the Classic 350 in October." was proposed as intent new,
  state sold; it matched the Classic by a shorter name and was refined:
  the disposal time was added while the item stayed owned.
Repairs: put a misplaced item time where it belongs; treat a different
ownership state of the named item as a change; and a record-level gate
that never writes an owned item with a disposal time, or with a time
phrase as its details or value.

D15: the model asked for the plan as "Spiti trip"; the stored plan is
"We're going with winter Spiti". The word lookup required every quoted
word, including the head noun "trip". Repair: plan/event head nouns are
ignored as quoted words.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_context_projection import record
from test_slice1_d12_d16 import _source

from jarvis.memory.learning_contracts import (
    EvidenceSpan,
    LearningBatch,
    LearningCandidate,
    LearningCatalog,
    LearningCatalogEntry,
    LearningResolutionBatch,
)
from jarvis.memory.learning_policy import LearningPolicy
from jarvis.memory.learning_reconciliation import LearningReconciler
from jarvis.memory.personal_context_projection import (
    ScopedContextSnapshot,
    parse_context_requests,
    project_personal_context,
)

LAB7 = json.loads(
    (
        Path(__file__).parent / "fixtures" / "lab7_d12_d15_d23_d17_recorded.json"
    ).read_text(encoding="utf-8")
)
S = LAB7["steps"]
D1_TEXT = (
    "I have a Royal Enfield Classic 350 from 2021, a Tata Tigor I bought in March"
    " 2017, and last month I got a Jimny."
)
TOLD = {"story-02": "2026-11-17", "story-12": "2026-11-19", "story-17": "2026-11-20"}


def _target(step):
    return S[step]["resolution"]["resolutions"][0]["target_id"]


def _recorded(step, index=0, text=None, **changes):
    """A recorded proposal; only the evidence turn id is rebound to the replay
    turn, and ``changes`` exist only for negative cases."""
    text = text or (D1_TEXT if step == "story-02" else S[step]["utterance"])
    source = _source(text, TOLD.get(step, "2026-11-20"))
    raw = {
        **json.loads(json.dumps(S[step]["extraction"]["candidates"][index])),
        **changes,
    }
    if "evidence" in changes or text != (
        D1_TEXT if step == "story-02" else S[step]["utterance"]
    ):
        raw["evidence"] = [{"turn_id": "x", "start": 0, "end": len(text)}]
    for span in raw["evidence"]:
        span["turn_id"] = source.turn_id
    return source, LearningCandidate.model_validate(raw)


def _stored_items():
    source, _ = _recorded("story-02")
    candidates = [
        _recorded("story-02", i)[1].model_copy(
            update={
                "evidence": [
                    EvidenceSpan(turn_id=source.turn_id, start=0, end=len(D1_TEXT))
                ]
            }
        )
        for i in range(3)
    ]
    plan = LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=candidates),
        LearningCatalog(),
        LearningResolutionBatch.model_validate(S["story-02"]["resolution"]),
    )
    ids = {
        "Royal Enfield Classic 350": _target("story-17"),
        "Tata Tigor": "tigor",
        "Jimny": _target("story-12"),
    }
    return {
        m.draft.value["label"]: LearningCatalogEntry(
            assertion_id=ids[m.draft.value["label"]],
            predicate=f"owned_item_{ids[m.draft.value['label']]}",
            category="owned_item",
            text=m.draft.normalized_text,
            value=json.dumps(m.draft.value, ensure_ascii=False),
            kind="vehicle",
        )
        for m in plan.mutations
    }


def _plan(entries, source, candidate, target):
    return LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(entries=list(entries)),
        LearningResolutionBatch(
            resolutions=[
                {"candidate_index": 0, "decision": "match", "target_id": target}
            ]
        ),
    )


# -- D12 ---------------------------------------------------------------------------


def test_lab7_d12_recorded_correction_put_the_month_in_details():
    _, candidate = _recorded("story-12")
    assert candidate.intent == "correction"
    assert (candidate.details, candidate.time_expression) == ("September", "September")
    assert candidate.acquired_expression is None


def test_lab7_d12_correction_now_corrects_the_purchase_month_only():
    entries = _stored_items()
    jimny = json.loads(entries["Jimny"].value)
    assert jimny["acquired"]["earliest"] == "2026-10-01"
    source, candidate = _recorded("story-12")
    assert LearningPolicy().evaluate(source, candidate).status == "eligible"
    plan = _plan(entries.values(), source, candidate, _target("story-12"))
    assert plan.outcomes == ()
    (mutation,) = plan.mutations
    value = mutation.draft.value
    assert mutation.action == "correct"
    assert (value["label"], value["value"]) == ("Jimny", "Jimny")
    assert "details" not in value  # lab 7 stored details "September"
    assert (value["acquired"]["earliest"], value["acquired"]["latest"]) == (
        "2026-09-01",
        "2026-09-30",
    )
    assert value["acquired"]["basis"] == "inferred_year"


def test_real_details_are_never_moved():
    entries = _stored_items()
    text = "Correction: the Jimny is the white one."
    source, candidate = _recorded(
        "story-12", text=text, details="the white one", time_expression=None
    )
    (mutation,) = _plan(
        entries.values(), source, candidate, _target("story-12")
    ).mutations
    value = mutation.draft.value
    assert value["details"] == "the white one"
    assert value["acquired"]["earliest"] == "2026-10-01"  # untouched


# -- D23 ---------------------------------------------------------------------------


def test_lab7_d23_recorded_sale_was_proposed_as_new_detail():
    _, candidate = _recorded("story-17")
    assert (candidate.intent, candidate.state) == ("new", "sold")
    assert (candidate.label, candidate.disposed_expression) == (
        "Classic 350",
        "October",
    )


def test_lab7_d23_sale_of_the_named_item_is_a_change_not_a_refine():
    entries = _stored_items()
    source, candidate = _recorded("story-17")
    assert LearningPolicy().evaluate(source, candidate).status == "eligible"
    plan = _plan(entries.values(), source, candidate, _target("story-17"))
    assert plan.outcomes == ()
    (mutation,) = plan.mutations
    assert mutation.action == "change"
    assert mutation.effective_at is None  # a month is not a change boundary
    value = mutation.draft.value
    assert value["state"] == "sold"
    assert value["label"] == "Royal Enfield Classic 350"
    assert (value["disposed"]["earliest"], value["disposed"]["latest"]) == (
        "2026-10-01",
        "2026-10-31",
    )
    assert (
        value["acquired"]
        == json.loads(entries["Royal Enfield Classic 350"].value)["acquired"]
    )


def test_a_new_item_with_the_same_state_still_refines_or_creates_as_before():
    entries = _stored_items()
    text = "My Classic 350 is the black one."
    source, candidate = _recorded(
        "story-17",
        text=text,
        state="owned",
        details="the black one",
        time_expression=None,
        disposed_expression=None,
    )
    (mutation,) = _plan(
        entries.values(), source, candidate, _target("story-17")
    ).mutations
    assert mutation.action == "refine"
    assert mutation.draft.value["state"] == "owned"


# -- the record-level gate -----------------------------------------------------------


def test_an_owned_item_is_never_written_with_a_disposal_time():
    entries = _stored_items()
    text = "My Classic 350, October."
    source, candidate = _recorded(
        "story-17", text=text, state="owned", disposed_expression="October"
    )
    plan = _plan(entries.values(), source, candidate, _target("story-17"))
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["inconsistent_item_state"]


def test_a_date_in_a_new_item_s_details_is_never_made_a_purchase_date():
    # Owner-evidence rule (2026-11-23): nothing says this date is the
    # purchase; it stays the owner's words in details, no relationship is
    # invented.
    text = "I have a Duster, March 2024."
    source, candidate = _recorded(
        "story-12",
        text=text,
        intent="new",
        label="Duster",
        value="Duster",
        details="March 2024",
        time_expression="March 2024",
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
    value = mutation.draft.value
    assert "acquired" not in value and value["details"] == "March 2024"


def test_details_repeating_a_placed_purchase_time_are_dropped():
    text = "I bought a Duster in March 2024."
    source, candidate = _recorded(
        "story-12",
        text=text,
        intent="new",
        label="Duster",
        value="Duster",
        details="March 2024",
        time_expression=None,
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
    value = mutation.draft.value
    assert "details" not in value and value["acquired"]["earliest"] == "2024-03-01"


def test_a_time_only_statement_that_is_not_a_correction_is_not_moved():
    text = "I bought a Duster in March 2024."
    source, candidate = _recorded(
        "story-12",
        text=text,
        intent="new",
        label="Duster",
        value="Duster",
        details=None,
        time_expression="March 2024",
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
    assert "acquired" not in mutation.draft.value


# -- D15 ---------------------------------------------------------------------------


def _plans():
    (read,) = S["story-13"]["tool_results"]
    out = []
    for i, fact in enumerate(read["result"]["facts"]):
        if fact["scope_key"] != "plan":
            continue
        label = fact["text"].split(": ", 1)[1].split(";")[0]
        r = record(label, f"plan-{i}")
        value = {
            **r.value,
            "category": "plan",
            "kind": "other",
            "state": fact["state"],
            "plan_status": fact["plan_status"],
            "slots": fact["slots"],
        }
        out.append(replace(r, value=value, predicate=f"plan_plan-{i}"))
    return out


def _lookup(records, quote, question, scope="plan"):
    return project_personal_context(
        ScopedContextSnapshot(tuple((r, scope) for r in records), ()),
        parse_context_requests(
            [{"scope_key": scope, "target_quote": quote}], question=question
        ),
    )


def test_lab7_d15_recorded_request_now_releases_only_the_decided_plan():
    (recorded,) = S["story-15"]["tool_results"]
    requests = recorded["arguments"]["requests"]
    assert {"scope_key": "plan", "target_quote": "Spiti trip"} in requests
    assert recorded["result"]["scopes"]["plan"] == "no_match"  # lab 7
    result = _lookup(_plans(), "Spiti trip", S["story-15"]["utterance"])
    (fact,) = result.facts
    assert fact["text"] == "We're going with winter Spiti"
    assert fact["slots"]["vehicle"]["value"] == "Jimny"


@pytest.mark.parametrize(
    "quote,question",
    [
        ("trip", "Which trip?"),
        ("plan", "Cancel the plan."),
        ("the trip", "Is the trip on?"),
    ],
)
def test_head_nouns_alone_never_match(quote, question):
    assert _lookup(_plans(), quote, question).status == "no_match"


def test_head_nouns_do_not_hide_ambiguity():
    plans = _plans() + [
        replace(
            record("Spiti bike ride", "extra"),
            value={**record("x").value, "category": "plan", "label": "Spiti bike ride"},
        )
    ]
    result = _lookup(plans, "Spiti trip", "Which vehicle for the Spiti trip?")
    assert result.status == "clarification_required"


def test_head_nouns_are_only_ignored_for_plans_and_events():
    vehicles = [record("Trip Master", "v")]
    result = _lookup(
        vehicles, "Trip", "When did I buy the Trip?", scope="owned_item.vehicle"
    )
    (fact,) = result.facts
    assert fact["text"] == "Trip Master"


# -- a correction's date is placed only from the owner's words and the stored item --


def _correction(entries, target, text, phrase, **changes):
    source, candidate = _recorded(
        "story-12",
        text=text,
        details=changes.pop("details", phrase),
        time_expression=phrase,
        **changes,
    )
    assert LearningPolicy().evaluate(source, candidate).status == "eligible", text
    return _plan(entries.values(), source, candidate, target)


@pytest.mark.parametrize(
    "text,phrase",
    [
        ("Correction: the Jimny was serviced in March, not February.", "March"),
        ("I misspoke, the Jimny's warranty runs to 2029, not 2028.", "2029"),
        ("I misspoke, the Jimny is a 2024 model, not 2023.", "2024"),
        ("Correction: the Jimny's insurance renews in June, not May.", "June"),
    ],
    ids=["service_date", "warranty_date", "model_year", "insurance_date"],
)
def test_other_dates_are_never_made_purchase_or_disposal_dates(text, phrase):
    entries = _stored_items()
    before = json.loads(entries["Jimny"].value)
    plan = _correction(entries, _target("story-12"), text, phrase)
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["date_role_conflict"]
    assert json.loads(entries["Jimny"].value) == before


def test_an_unnamed_replaced_date_uses_the_item_s_only_stored_date():
    entries = _stored_items()
    plan = _correction(
        entries,
        _target("story-12"),
        "Correction: the Jimny is from September.",
        "September",
    )
    (mutation,) = plan.mutations
    assert mutation.draft.value["acquired"]["earliest"] == "2026-09-01"


def test_an_unnamed_replaced_date_with_two_stored_dates_is_unclear():
    entries = _stored_items()
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
    entries["Tata Tigor"] = LearningCatalogEntry(
        assertion_id="tigor",
        predicate="owned_item_tigor",
        category="owned_item",
        text="owned_item.vehicle: Tata Tigor",
        value=json.dumps(tigor),
        kind="vehicle",
    )
    plan = _correction(
        entries,
        "tigor",
        "Correction: the Tigor is October.",
        "October",
        label="Tigor",
        value="Tigor",
        state="sold",
    )
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["time_meaning_unclear"]


def test_conflicting_wording_blocks_the_unique_date_fallback():
    entries = _stored_items()
    before = json.loads(entries["Jimny"].value)
    plan = _correction(
        entries,
        _target("story-12"),
        "Correction: the Jimny's service is from September.",
        "September",
    )
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["date_role_conflict"]
    assert json.loads(entries["Jimny"].value) == before


def test_a_replaced_date_matching_two_stored_dates_is_unclear():
    entries = _stored_items()
    tigor = json.loads(entries["Tata Tigor"].value)
    october = {
        "expression": "October",
        "precision": "month",
        "earliest": "2026-10-01",
        "latest": "2026-10-31",
        "basis": "stated",
    }
    tigor.update(state="sold", acquired=october, disposed=october)
    entries["Tata Tigor"] = LearningCatalogEntry(
        assertion_id="tigor",
        predicate="owned_item_tigor",
        category="owned_item",
        text="owned_item.vehicle: Tata Tigor",
        value=json.dumps(tigor),
        kind="vehicle",
    )
    plan = _correction(
        entries,
        "tigor",
        "I misspoke, the Tigor is September, not October.",
        "September",
        label="Tigor",
        value="Tigor",
        state="sold",
    )
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["time_meaning_unclear"]


def test_a_corrected_sale_date_is_placed_when_it_replaces_the_stored_one():
    entries = _stored_items()
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
    entries["Tata Tigor"] = LearningCatalogEntry(
        assertion_id="tigor",
        predicate="owned_item_tigor",
        category="owned_item",
        text="owned_item.vehicle: Tata Tigor",
        value=json.dumps(tigor),
        kind="vehicle",
    )
    plan = _correction(
        entries,
        "tigor",
        "I misspoke, I sold the Tigor in October, not November.",
        "October",
        label="Tigor",
        value="Tigor",
        state="sold",
    )
    (mutation,) = plan.mutations
    value = mutation.draft.value
    assert (value["disposed"]["earliest"], value["disposed"]["latest"]) == (
        "2026-10-01",
        "2026-10-31",
    )
    assert value["acquired"] == tigor["acquired"] and "details" not in value


# -- collisions: another date role that matches a stored date, or sits in the
# purchase/disposal field itself (owner check 2026-11-23 15:15) -------------------


def _jimny_bought(year_expression="2024", earliest="2024-01-01", latest="2024-12-31"):
    entries = _stored_items()
    jimny = json.loads(entries["Jimny"].value)
    jimny["acquired"] = {
        "expression": year_expression,
        "precision": "year",
        "earliest": earliest,
        "latest": latest,
        "basis": "stated",
    }
    entries["Jimny"] = LearningCatalogEntry(
        assertion_id=_target("story-12"),
        predicate=f"owned_item_{_target('story-12')}",
        category="owned_item",
        text="owned_item.vehicle: Jimny",
        value=json.dumps(jimny),
        kind="vehicle",
    )
    return entries, jimny


def test_model_year_equal_to_the_purchase_year_never_updates_the_purchase():
    entries, _jimny = _jimny_bought()
    plan = _correction(
        entries,
        _target("story-12"),
        "I misspoke, the Jimny is a 2025 model, not 2024.",
        "2025",
    )
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["date_role_conflict"]


@pytest.mark.parametrize(
    "text,phrase",
    [
        ("Correction: the Jimny was serviced in March, not February.", "March"),
        ("I misspoke, the Jimny's warranty runs to 2029, not 2024.", "2029"),
        ("I misspoke, the Jimny is a 2025 model, not 2024.", "2025"),
    ],
    ids=["service_in_acquired", "warranty_in_acquired", "model_year_in_acquired"],
)
def test_a_model_supplied_purchase_date_with_another_role_is_refused(text, phrase):
    entries, _jimny = _jimny_bought()
    plan = _correction(
        entries,
        _target("story-12"),
        text,
        phrase,
        details=None,
        acquired_expression=phrase,
    )
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["date_role_conflict"]


def test_a_model_supplied_disposal_date_with_another_role_is_not_kept():
    entries = _stored_items()
    text = "I sold the Tigor; its warranty ended in March."
    source, candidate = _recorded(
        "story-17",
        text=text,
        intent="change",
        label="Tigor",
        value="Tigor",
        state="sold",
        time_expression="March",
        disposed_expression="March",
    )
    (mutation,) = _plan(entries.values(), source, candidate, "tigor").mutations
    value = mutation.draft.value
    assert value["state"] == "sold" and "disposed" not in value


def test_a_new_item_s_model_year_in_the_purchase_field_is_not_kept():
    text = "I have a 2024 model Duster."
    source, candidate = _recorded(
        "story-12",
        text=text,
        intent="new",
        label="Duster",
        value="Duster",
        details=None,
        time_expression="2024",
        acquired_expression="2024",
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
    assert "acquired" not in mutation.draft.value


def test_a_purchase_date_in_its_own_clause_is_kept_beside_a_service_date():
    text = "I bought the Duster in March and serviced it in June."
    source, candidate = _recorded(
        "story-12",
        text=text,
        intent="new",
        label="Duster",
        value="Duster",
        details=None,
        time_expression="March",
        acquired_expression="March",
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
    assert mutation.draft.value["acquired"]["expression"] == "March"


def test_matching_a_known_item_with_only_a_conflicting_date_is_recorded():
    entries = _stored_items()
    text = "The Jimny is a 2024 model."
    source, candidate = _recorded(
        "story-12",
        text=text,
        intent="new",
        details=None,
        time_expression="2024",
        acquired_expression="2024",
    )
    plan = _plan(entries.values(), source, candidate, _target("story-12"))
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["date_role_conflict"]
