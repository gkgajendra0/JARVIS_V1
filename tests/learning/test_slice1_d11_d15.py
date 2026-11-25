"""Run 6 (lab e91da771) D11 and D15, reproduced from the recorded outputs.

D11: "Cancel the Goa plan." cancelled the stored plan (and renamed it "Goa
plan" from the proposal's label), but the reply's lookup with target_quote
"Goa" returned no_match: a target quote matched only an exactly equal label.
The answer then said no Goa plan existed. Fixes: a lookup falls back to a
unique whole-word reference within the requested scope (never substrings;
several matches ask which one), and a status change of the plan it names
keeps that plan's name.

D15: the decided plan never reached the answer model (after the restart only
vehicles were in context, and only vehicles were requested). Fix (instructions,
general): for advice about something the owner may have planned or decided,
include plan/event narrowed to the named activity, and leave unrelated plans
out. The lab grader now checks that the relevant plan reached the model and
that the answer is consistent with it.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from test_context_projection import record, snap
from test_slice1_d12_d16 import _source

from jarvis.memory.learning_contracts import (
    LearningBatch,
    LearningCandidate,
    LearningCatalog,
    LearningCatalogEntry,
    LearningResolutionBatch,
)
from jarvis.memory.learning_reconciliation import LearningReconciler
from jarvis.memory.personal_context_projection import (
    ScopedContextSnapshot,
    parse_context_requests,
    project_personal_context,
)

RUN6 = json.loads(
    (Path(__file__).parent / "fixtures" / "run6_d11_d15_recorded.json").read_text(
        encoding="utf-8"
    )
)
STEPS = RUN6["steps"]
GOA_ID = STEPS["story-11"]["resolution"]["resolutions"][0]["target_id"]


# -- D11: the lookup -------------------------------------------------------------


def _plan_record(label, ident, **value):
    r = record(label, ident)
    data = {
        **r.value,
        "category": "plan",
        "kind": "other",
        "state": value.pop("state", "planned"),
        **value,
    }
    return replace(r, value=data, predicate="plan_" + ident)


def _run6_plans():
    """The three plans exactly as run 6's story-13 lookup released them."""
    (read,) = STEPS["story-13"]["tool_results"]
    plans = [f for f in read["result"]["facts"] if f["scope_key"] == "plan"]
    out = []
    for i, fact in enumerate(plans):
        label = fact["text"].split(": ", 1)[1].split(";")[0]
        value = fact["text"].split("value=", 1)[1].split(";")[0]
        out.append(
            _plan_record(
                label,
                f"plan-{i}",
                value=value,
                state=fact["state"],
                plan_status=fact["plan_status"],
                slots=fact["slots"],
            )
        )
    return out


def _plan_snapshot(records):
    return ScopedContextSnapshot(tuple((r, "plan") for r in records), ())


def _lookup(records, quote, question):
    return project_personal_context(
        _plan_snapshot(records),
        parse_context_requests(
            [{"scope_key": "plan", "target_quote": quote}], question=question
        ),
    )


def test_run6_d11_recorded_lookup_now_finds_the_cancelled_goa_plan():
    (recorded,) = STEPS["story-11"]["tool_results"]
    assert recorded["arguments"] == {
        "requests": [{"scope_key": "plan", "target_quote": "Goa"}]
    }
    assert recorded["result"]["status"] == "no_match"  # run 6
    result = _lookup(_run6_plans(), "Goa", STEPS["story-11"]["utterance"])
    assert result.status == "selected"
    (fact,) = result.facts
    assert fact["text"] == "Goa plan"
    assert fact["plan_status"] == "cancelled"


def test_exact_label_is_preferred_over_a_word_reference():
    plans = [_plan_record("Goa", "a"), _plan_record("Goa beach trip", "b")]
    (fact,) = _lookup(plans, "Goa", "Cancel Goa.").facts
    assert fact["text"] == "Goa"


def test_the_whole_stored_name_inside_the_quote_is_found():
    # Stored "Goa" (kept name), the owner says "the Goa plan".
    plans = [_plan_record("Goa", "a"), _plan_record("Rishikesh trip", "b")]
    (fact,) = _lookup(plans, "Goa plan", "Cancel the Goa plan.").facts
    assert fact["text"] == "Goa"


def test_a_word_shared_by_several_plans_asks_which_one():
    plans = [
        _plan_record("Goa beach trip", "a"),
        _plan_record("Goa food trip", "b"),
        _plan_record("Rishikesh trip", "c"),
    ]
    result = _lookup(plans, "Goa", "Cancel the Goa plan.")
    assert result.status == "clarification_required" and result.facts == ()
    assert result.reason == "ambiguous_target"
    # Two plans whose whole names are inside the quote: also ambiguous.
    both = [_plan_record("Goa", "a"), _plan_record("Beach", "b")]
    assert _lookup(both, "Goa beach plan", "Cancel the Goa beach plan.").status == (
        "clarification_required"
    )


def test_no_substring_or_partial_word_matches():
    plans = [_plan_record("Goa trip", "a")]
    for quote, question in (
        ("Go", "Cancel Go."),
        ("oa", "Is oa on?"),
        ("Goan", "The Goan trip?"),
    ):
        assert _lookup(plans, quote, question).status == "no_match", quote


def test_articles_alone_never_single_out_and_never_count():
    plans = [_plan_record("Goa trip", "a")]
    # An article names no item: the plan category is not narrowed (Paid lab 3
    # D4); the reply sees it as a generic target.
    result = _lookup(plans, "the", "Cancel the plan.")
    assert result.generic_targets == ("plan",)
    (fact,) = _lookup(plans, "the Goa", "Cancel the Goa plan.").facts
    assert fact["text"] == "Goa trip"


def test_a_word_reference_never_leaves_its_requested_scope():
    vehicle = record("Goa", "v")  # an owned vehicle that happens to be "Goa"
    snapshot = ScopedContextSnapshot(
        (
            (vehicle, "owned_item.vehicle"),
            (_plan_record("Rishikesh trip", "p"), "plan"),
        ),
        (),
    )
    result = project_personal_context(
        snapshot,
        parse_context_requests(
            [{"scope_key": "plan", "target_quote": "Goa"}],
            question="Cancel the Goa plan.",
        ),
    )
    assert result.status == "no_match" and result.facts == ()


def test_an_unrelated_plan_is_not_released_for_a_named_trip():
    # D15 shape: narrowing to the named trip releases only that plan.
    result = _lookup(_run6_plans(), "Spiti", STEPS["story-15"]["utterance"])
    (fact,) = result.facts
    assert fact["text"] == "winter Spiti"
    assert fact["slots"]["vehicle"]["value"] == "Jimny"
    assert "Goa" not in json.dumps(result.facts)
    assert "Rishikesh" not in json.dumps(result.facts)


def test_existing_vehicle_lookups_are_unchanged():
    vehicles = snap(record("Honda City", "a"), record("Tata Nexon", "b"))
    project = project_personal_context(
        vehicles,
        parse_context_requests(
            [{"scope_key": "owned_item.vehicle", "target_quote": "City"}],
            question="When did I buy the City?",
        ),
    )
    (fact,) = project.facts
    assert fact["text"] == "Honda City"


# -- D11: the stored plan keeps its name -----------------------------------------


def _replay(step, text=None):
    text = (
        text
        or {
            "story-08": "Maybe we'll do Goa this winter.",
            "story-11": STEPS["story-11"]["utterance"],
        }[step]
    )
    source = _source(text, "2026-11-19")
    (raw,) = STEPS[step]["extraction"]["candidates"]
    raw = json.loads(json.dumps(raw))
    for span in raw["evidence"]:
        span["turn_id"] = source.turn_id
    return source, LearningCandidate.model_validate(raw)


def _goa_entry(assertion_id=GOA_ID, label=None):
    source, candidate = _replay("story-08")
    plan = LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(),
        LearningResolutionBatch.model_validate(STEPS["story-08"]["resolution"]),
    )
    (mutation,) = plan.mutations
    value = mutation.draft.value
    if label:
        value = {**value, "label": label, "value": label}
    return LearningCatalogEntry(
        assertion_id=assertion_id,
        predicate=f"plan_{assertion_id}",
        category="plan",
        text=f"plan.other: {value['label']}",
        value=json.dumps(value, ensure_ascii=False),
        kind="other",
    )


def _cancel(entries, target=GOA_ID):
    source, candidate = _replay("story-11")
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


def test_run6_d11_cancelling_the_goa_plan_keeps_its_name():
    entry = _goa_entry()
    assert json.loads(entry.value)["label"] == "Goa"
    (mutation,) = _cancel([entry]).mutations  # recorded label "Goa plan"
    assert mutation.action == "change"
    value = mutation.draft.value
    assert (value["label"], value["value"]) == ("Goa", "Goa")
    assert value["plan_status"] == "cancelled"
    assert value["slots"]["when"]["value"] == "this winter"  # kept


def test_a_label_that_does_not_name_the_plan_still_takes_the_new_name():
    # The stored plan is called something the proposal does not contain.
    entry = _goa_entry(label="beach holiday")
    (mutation,) = _cancel([entry]).mutations
    assert mutation.draft.value["label"] == "Goa plan"


def test_two_plans_inside_the_label_keep_existing_behaviour():
    # "plan" is a head noun, so "Goa plan" names the stored "Goa" plan alone
    # when nothing else is called Goa. With two plans both called Goa the words
    # no longer pick one out, and the proposal's label is used as before.
    goa = _goa_entry()
    other = _goa_entry(assertion_id="plan-2", label="Goa")
    (mutation,) = _cancel([goa, other]).mutations
    assert mutation.draft.value["label"] == "Goa plan"


def test_a_head_noun_alone_never_names_another_plan():
    goa = _goa_entry()
    other = _goa_entry(assertion_id="plan-2", label="plan")
    (mutation,) = _cancel([goa, other]).mutations
    assert (mutation.draft.value["label"], mutation.draft.value["value"]) == (
        "Goa",
        "Goa",
    )


# -- D15: guidance -----------------------------------------------------------------


def test_advice_guidance_asks_for_relevant_plans_and_excludes_unrelated_ones():
    from jarvis.voice.agent import PERSONAL_LEARNING_QUERY_INSTRUCTIONS as text

    flat = " ".join(text.split())
    assert "saved plans and decisions could change the answer" in flat
    assert "include plan or event as well" in flat
    assert "let a decided detail change the advice" in flat
    assert "leave out plans and categories unrelated to the question" in flat
    assert "Spiti" not in flat and "Jimny" not in flat  # general, not the case
