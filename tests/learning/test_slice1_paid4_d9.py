"""D9 ("We're going to Spiti in January, Thar or no Thar." / "Either way,
January."), from both recorded Paid failures, unmodified:

- Paid lab 4 (ef365bbf, fixtures/paid4_d9_recorded.json): vehicle options
  ["Thar", "no Thar"], certainty uncertain -> stored as an undecided choice.
- Paid lab 6 (4be3ebbe, fixtures/paid6_d9_recorded.json): vehicle options
  ["Thar"], tentative -> promoted by code to a tentative vehicle value.

The gap is general, not a phrase: code turned the model's own uncertainty,
and a lone mention, into stored meaning. General rules now (no word lists):
a detail is decided only by a value the proposal states (options are never
promoted); alternatives need two or more distinct options (a lone option is a
mention); a slot or fact the proposal marks uncertain is not saved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_slice1_d12_d16 import StampedConversation, _source

from jarvis.authority.personal_learning import POLICY_VERSION
from jarvis.memory.learning_contracts import (
    AcceptedLearningSource,
    EvidenceSpan,
    LearningBatch,
    LearningCandidate,
    LearningCatalog,
    LearningCatalogEntry,
    LearningResolutionBatch,
)
from jarvis.memory.learning_policy import LearningPolicy, ground_plan_label
from jarvis.memory.learning_reconciliation import LearningReconciler

FIXTURES = Path(__file__).parent / "fixtures"
LAB4 = json.loads((FIXTURES / "paid4_d9_recorded.json").read_text(encoding="utf-8"))
LAB6 = json.loads((FIXTURES / "paid6_d9_recorded.json").read_text(encoding="utf-8"))


def _replay(recorded, step, steps=None):
    """The recorded proposal unmodified; only evidence turn ids are rebound to
    the replayed turns of one conversation (recorded first turn -> replayed
    first turn, recorded current turn -> replayed current turn)."""
    s = recorded["steps"]
    steps = steps or (step,)
    c = StampedConversation()
    c.start()
    turns = {k: c.say(s[k]["utterance"], s[k]["told_at"][:10]) for k in steps}
    source = AcceptedLearningSource.from_turn("runtime", c, turns[step], now=100)
    first_id = s["idiom-01"]["extraction"]["candidates"][0]["evidence"][0]["turn_id"]
    (raw,) = s[step]["extraction"]["candidates"]
    raw = json.loads(json.dumps(raw))
    for span in raw["evidence"]:
        span["turn_id"] = (
            turns["idiom-01"].turn_id
            if span["turn_id"] == first_id
            else turns[step].turn_id
        )
    return source, ground_plan_label(source, LearningCandidate.model_validate(raw))


def _plan(source, candidate, entries=(), resolution=None):
    return LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(entries=list(entries)),
        LearningResolutionBatch.model_validate(
            resolution or {"resolutions": [{"candidate_index": 0, "decision": "new"}]}
        ),
    )


def _created(recorded):
    source, candidate = _replay(recorded, "idiom-01")
    assert LearningPolicy().evaluate(source, candidate).status == "eligible"
    (mutation,) = _plan(source, candidate).mutations
    return mutation.draft.value


@pytest.mark.parametrize("recorded", [LAB4, LAB6], ids=["lab4-pair", "lab6-single"])
def test_both_recorded_first_turns_store_spiti_january_and_no_vehicle(recorded):
    value = _created(recorded)
    slots = value["slots"]
    assert "vehicle" not in slots
    assert slots["destination"] == {
        "value": "Spiti",
        "options": [],
        "certainty": "confirmed",
    }
    assert slots["when"] == {
        "value": "January",
        "options": [],
        "certainty": "confirmed",
    }
    assert value["plan_status"] == "planned"
    assert "Thar" not in json.dumps(slots)


def test_the_recorded_shapes_are_the_ones_that_failed():
    lab4 = LAB4["steps"]["idiom-01"]["extraction"]["candidates"][0]["slots"]["vehicle"]
    lab6 = LAB6["steps"]["idiom-01"]["extraction"]["candidates"][0]["slots"]["vehicle"]
    assert (lab4["options"], lab4["certainty"]) == (["Thar", "no Thar"], "uncertain")
    assert (lab6["value"], lab6["options"], lab6["certainty"]) == (
        None,
        ["Thar"],
        "tentative",
    )


def test_both_recorded_second_turns_still_change_nothing():
    # Lab 4: cites only the earlier turn (policy: unsupported_value).
    source, candidate = _replay(LAB4, "idiom-02", ("idiom-01", "idiom-02"))
    assert LearningPolicy().evaluate(source, candidate).reason == "unsupported_value"
    # Lab 6: matched the stored plan but is a "new" fact with nothing decided.
    created = _created(LAB6)
    entry = LearningCatalogEntry(
        assertion_id="plan-spiti",
        predicate="plan_plan-spiti",
        category="plan",
        text=f"plan.other: {created['label']}",
        value=json.dumps(created),
        kind="other",
    )
    source, candidate = _replay(LAB6, "idiom-02", ("idiom-01", "idiom-02"))
    assert LearningPolicy().evaluate(source, candidate).status == "eligible"
    resolution = {
        "resolutions": [
            {"candidate_index": 0, "decision": "match", "target_id": "plan-spiti"}
        ]
    }
    plan = _plan(source, candidate, [entry], resolution)
    assert plan.mutations == ()


# -- general rules over varied wording -----------------------------------------


def _say(text, slots, *, label, certainty="confirmed", category="plan", **extra):
    source = _source(text, "2026-11-18")
    fields = {
        "category": category,
        "kind": extra.pop("kind", "other"),
        "intent": "new",
        "label": label,
        "value": extra.pop("value", label),
        "state": extra.pop("state", "planned"),
        "certainty": certainty,
        "evidence": [EvidenceSpan(turn_id=source.turn_id, start=0, end=len(text))],
        **extra,
    }
    if category == "plan":
        fields["plan_status"] = "planned"
        fields["slots"] = {
            name: {"value": v, "options": list(o), "certainty": c}
            for name, (v, o, c) in slots.items()
        }
    return source, LearningCandidate(**fields)


def _stored_slots(text, slots, label="Spiti"):
    source, candidate = _say(text, slots, label=label)
    assert LearningPolicy().evaluate(source, candidate).status == "eligible", text
    (mutation,) = _plan(source, candidate).mutations
    return mutation.draft.value.get("slots", {})


@pytest.mark.parametrize(
    "text,vehicle",
    [
        # Mentions only: a lone option, whatever the wording.
        ("Spiti in January, Thar or no Thar.", (None, ["Thar"], "tentative")),
        (
            "Spiti in January, with or without the Jimny.",
            (None, ["Jimny"], "confirmed"),
        ),
        ("Spiti in January, Gypsy ho ya na ho.", (None, ["Gypsy"], "tentative")),
        ("Spiti in January, never mind the Scorpio.", (None, ["Scorpio"], "tentative")),
        # The proposal itself is unsure what the owner meant about the vehicle.
        (
            "Spiti in January, Thar or no Thar.",
            (None, ["Thar", "no Thar"], "uncertain"),
        ),
        ("Spiti in January, maybe Thar types.", ("Thar", [], "uncertain")),
    ],
)
def test_a_mention_or_an_unclear_detail_is_never_stored(text, vehicle):
    slots = _stored_slots(
        text,
        {"vehicle": vehicle, "when": ("January", [], "confirmed")},
    )
    assert "vehicle" not in slots, text
    assert slots["when"]["value"] == "January"  # unrelated detail kept


@pytest.mark.parametrize(
    "text,options,certainty",
    [
        ("Spiti in January, Thar or Jimny.", ["Thar", "Jimny"], "tentative"),
        (
            "Spiti in January, Thar or Jimny, not sure yet.",
            ["Thar", "Jimny"],
            "confirmed",
        ),
        ("Spiti, Thar ya Gypsy ya Jimny.", ["Thar", "Gypsy", "Jimny"], "tentative"),
    ],
)
def test_genuine_alternatives_stay_undecided_choices(text, options, certainty):
    slots = _stored_slots(text, {"vehicle": (None, options, certainty)})
    assert slots["vehicle"] == {
        "value": None,
        "options": options,
        "certainty": "tentative",
    }


@pytest.mark.parametrize(
    "text,value,certainty",
    [
        ("We'll take the Jimny to Spiti.", "Jimny", "confirmed"),
        ("Thar or no Thar, we'll take the Jimny to Spiti.", "Jimny", "confirmed"),
        ("We might take the Jimny to Spiti.", "Jimny", "tentative"),
    ],
)
def test_a_stated_detail_is_stored_with_its_own_certainty(text, value, certainty):
    slots = _stored_slots(text, {"vehicle": (value, [], certainty)})
    assert slots["vehicle"] == {"value": value, "options": [], "certainty": certainty}


def test_a_value_beside_options_is_still_an_undecided_choice():
    # Two options and a value: the proposal is inconsistent; nothing is decided.
    slots = _stored_slots(
        "Spiti, Thar or Jimny.", {"vehicle": ("Thar", ["Thar", "Jimny"], "confirmed")}
    )
    assert slots["vehicle"]["value"] is None


def test_a_fact_the_proposal_marks_uncertain_is_never_saved():
    for category, label, kw in (
        ("owned_item", "Thar", {"kind": "vehicle", "state": "owned"}),
        ("plan", "Spiti", {}),
    ):
        text = "Thar or no Thar, Spiti in January."
        source, candidate = _say(
            text, {}, label=label, category=category, certainty="uncertain", **kw
        )
        eligibility = LearningPolicy().evaluate(source, candidate)
        assert (eligibility.status, eligibility.reason) == ("drop", "meaning_unclear")


def test_a_mention_never_creates_ownership():
    # "Thar or no Thar" proposed as an owned Thar would need the model to say
    # so; when it is unsure it is dropped; the vehicle slot never owns anything.
    value = _created(LAB4)
    assert value["category"] == "plan"


def test_options_the_owner_never_said_are_still_refused():
    source, candidate = _say(
        "We're going to Spiti in January, Thar or no Thar.",
        {"vehicle": (None, ["Thar", "Jimny"], "tentative")},
        label="Spiti",
    )
    assert LearningPolicy().evaluate(source, candidate).reason == "unsupported_detail"


# -- clarification resolves without repeating what is known ------------------------


def _stored_entry(value, assertion_id="plan-spiti"):
    return LearningCatalogEntry(
        assertion_id=assertion_id,
        predicate=f"plan_{assertion_id}",
        category="plan",
        text=f"plan.other: {value['label']}",
        value=json.dumps(value),
        kind="other",
    )


def test_a_later_clear_answer_adds_the_detail_and_keeps_the_rest():
    # After "Thar or no Thar" (nothing stored about the vehicle) the owner
    # answers a clarification; the plan gains the vehicle and keeps the rest.
    stored = _created(LAB6)  # Spiti, January, no vehicle
    entry = _stored_entry(stored)
    c = StampedConversation()
    c.start()
    first = c.say(LAB6["steps"]["idiom-01"]["utterance"], "2026-11-18")
    answer = c.say("We'll take the Thar.", "2026-11-18")
    source = AcceptedLearningSource.from_turn("runtime", c, answer, now=100)
    spiti = first.text.index("Spiti")
    candidate = LearningCandidate(
        category="plan",
        kind="other",
        intent="new",
        label="Spiti",
        value="Spiti",
        state="planned",
        certainty="confirmed",
        plan_status="planned",
        slots={"vehicle": {"value": "Thar", "options": [], "certainty": "confirmed"}},
        evidence=[
            EvidenceSpan(turn_id=first.turn_id, start=spiti, end=spiti + 5),
            EvidenceSpan(turn_id=answer.turn_id, start=0, end=len(answer.text)),
        ],
    )
    assert LearningPolicy().evaluate(source, candidate).status == "eligible"
    resolution = {
        "resolutions": [
            {"candidate_index": 0, "decision": "match", "target_id": entry.assertion_id}
        ]
    }
    (mutation,) = _plan(source, candidate, [entry], resolution).mutations
    assert mutation.expected_assertion_id == entry.assertion_id
    slots = mutation.draft.value["slots"]
    assert slots["vehicle"] == {
        "value": "Thar",
        "options": [],
        "certainty": "confirmed",
    }
    assert slots["when"] == stored["slots"]["when"]
    assert slots["destination"] == stored["slots"]["destination"]


def test_a_stored_choice_is_not_decided_by_an_unclear_or_lone_mention():
    value = {
        "schema": POLICY_VERSION,
        "category": "plan",
        "kind": "other",
        "label": "Spiti trip",
        "value": "Spiti trip",
        "state": "planned",
        "certainty": "confirmed",
        "plan_status": "planned",
        "slots": {
            "vehicle": {
                "value": None,
                "options": ["Thar", "Jimny"],
                "certainty": "tentative",
            }
        },
    }
    entry = _stored_entry(value)
    for vehicle in ((None, ["Thar"], "tentative"), ("Thar", [], "uncertain")):
        source, candidate = _say(
            "Spiti trip, Thar or no Thar.", {"vehicle": vehicle}, label="Spiti trip"
        )
        plan = _plan(
            source,
            candidate,
            [entry],
            {
                "resolutions": [
                    {
                        "candidate_index": 0,
                        "decision": "match",
                        "target_id": entry.assertion_id,
                    }
                ]
            },
        )
        # Nothing new is decided, so the stored choice (Thar or Jimny,
        # undecided) is left exactly as it was.
        assert plan.mutations == () and plan.outcomes == (), vehicle


def test_reply_guidance_asks_when_unclear_without_repeating_known_details():
    from jarvis.voice.agent import PERSONAL_LEARNING_QUERY_INSTRUCTIONS as text

    flat = " ".join(text.split())
    assert "ask briefly what they mean" in flat
    assert "do not ask again for details already known" in flat
