"""Paid lab 4 (ef365bbf, slice1-acceptance-paid-4-d4) D9, replayed from the
recorded outputs (fixtures/paid4_d9_recorded.json, unmodified).

"We're going to Spiti in January, Thar or no Thar." was proposed with vehicle
options ["Thar", "no Thar"] (uncertain), and stored as an undecided vehicle
choice. "X or no X" says the trip happens regardless of X; it is not a choice
between alternatives. Options that are only something and its own negation
are no longer stored as alternatives (learning_values.complementary_options);
genuine alternatives are untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_slice1_d12_d16 import _source

from jarvis.memory.learning_contracts import (
    EvidenceSpan,
    LearningBatch,
    LearningCandidate,
    LearningCatalog,
    LearningCatalogEntry,
    LearningResolutionBatch,
)
from jarvis.memory.learning_policy import LearningPolicy, ground_plan_label
from jarvis.memory.learning_reconciliation import LearningReconciler
from jarvis.memory.learning_values import complementary_options

D9 = json.loads(
    (Path(__file__).parent / "fixtures" / "paid4_d9_recorded.json").read_text(
        encoding="utf-8"
    )
)
S = D9["steps"]


def _conversation_source(*steps):
    """One conversation holding the given recorded turns; the source is the
    last of them (as in the lab)."""
    from test_slice1_d12_d16 import StampedConversation

    from jarvis.memory.learning_contracts import AcceptedLearningSource

    c = StampedConversation()
    c.start()
    turns = [c.say(S[step]["utterance"], S[step]["told_at"][:10]) for step in steps]
    source = AcceptedLearningSource.from_turn("runtime", c, turns[-1], now=100)
    return source, {step: turn.turn_id for step, turn in zip(steps, turns, strict=True)}


FIRST_TURN = S["idiom-01"]["extraction"]["candidates"][0]["evidence"][0]["turn_id"]


def _replay(step, steps=None):
    """The recorded proposal; only its evidence turn ids are rebound to the
    replay turns (the recorded first turn id -> the replayed first turn)."""
    source, ids = _conversation_source(*(steps or (step,)))
    (raw,) = S[step]["extraction"]["candidates"]
    raw = json.loads(json.dumps(raw))
    for span in raw["evidence"]:
        span["turn_id"] = (
            ids["idiom-01"] if span["turn_id"] == FIRST_TURN else ids[step]
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


def _entry(value, assertion_id="plan-spiti"):
    return LearningCatalogEntry(
        assertion_id=assertion_id,
        predicate=f"plan_{assertion_id}",
        category="plan",
        text=f"plan.other: {value['label']}",
        value=json.dumps(value),
        kind="other",
    )


def test_recorded_first_turn_stores_spiti_january_and_no_vehicle_choice():
    source, candidate = _replay("idiom-01")
    assert LearningPolicy().evaluate(source, candidate).status == "eligible"
    assert candidate.slots.vehicle.options == ["Thar", "no Thar"]  # as recorded
    (mutation,) = _plan(source, candidate).mutations
    value = mutation.draft.value
    assert "vehicle" not in value["slots"]
    assert value["slots"]["destination"] == {
        "value": "Spiti",
        "options": [],
        "certainty": "confirmed",
    }
    assert value["slots"]["when"] == {
        "value": "January",
        "options": [],
        "certainty": "confirmed",
    }
    assert value["plan_status"] == "planned" and value["category"] == "plan"
    assert "Thar" not in json.dumps(value["slots"])


def test_recorded_second_turn_still_changes_nothing():
    first_source, first = _replay("idiom-01")
    (created,) = _plan(first_source, first).mutations
    source, candidate = _replay("idiom-02", steps=("idiom-01", "idiom-02"))
    # The recorded proposal cites only the earlier turn: not this turn's words.
    assert LearningPolicy().evaluate(source, candidate).reason == "unsupported_value"
    assert S["idiom-02"]["status"]["committed"] == 0
    assert "vehicle" not in created.draft.value["slots"]


@pytest.mark.parametrize(
    "options",
    [
        ["Thar", "no Thar"],
        ["with the Jimny", "without the Jimny"],
        ["Thar", "Thar nahi"],
        ["Thar", "not"],
        ["the Thar", "no Thar"],
    ],
)
def test_something_or_its_negation_is_an_idiom_not_a_choice(options):
    assert complementary_options(options) == set(options)


@pytest.mark.parametrize(
    "options",
    [
        ["Thar", "Jimny"],
        ["Ladakh", "winter Spiti"],
        ["Thar", "no car"],  # different things: a genuine choice
        ["Ladakh", "no trip at all"],
        ["Nothing Phone", "iPhone"],
        ["Nokia", "Pixel"],
    ],
)
def test_genuine_alternatives_are_never_treated_as_an_idiom(options):
    assert complementary_options(options) == set()


def _say(text, slots, label="Spiti", value=None, certainty="tentative"):
    source = _source(text, "2026-11-18")
    candidate = LearningCandidate(
        category="plan",
        kind="other",
        intent="new",
        label=label,
        value=value or text.rstrip("."),
        state="planned",
        plan_status="planned",
        slots={
            name: (
                {"value": v, "options": list(o), "certainty": certainty}
                if (v or o)
                else None
            )
            for name, (v, o) in slots.items()
        },
        evidence=[EvidenceSpan(turn_id=source.turn_id, start=0, end=len(text))],
    )
    return source, candidate


def _stored(text, slots, **kw):
    source, candidate = _say(text, slots, **kw)
    assert LearningPolicy().evaluate(source, candidate).status == "eligible", text
    (mutation,) = _plan(source, candidate).mutations
    return mutation.draft.value.get("slots", {})


def test_genuine_vehicle_alternatives_are_kept_undecided():
    slots = _stored(
        "Spiti trip in January, Thar or Jimny.",
        {"vehicle": (None, ["Thar", "Jimny"]), "when": ("January", ())},
    )
    assert slots["vehicle"] == {
        "value": None,
        "options": ["Thar", "Jimny"],
        "certainty": "tentative",
    }
    assert slots["when"]["value"] == "January"


def test_with_or_without_and_hinglish_negation_store_no_choice():
    for text, options in (
        (
            "Spiti in January, with the Jimny or without the Jimny.",
            ["with the Jimny", "without the Jimny"],
        ),
        ("Spiti in January, Thar ya Thar nahi.", ["Thar", "Thar nahi"]),
        ("Spiti in January, Thar or not.", ["Thar", "not"]),
    ):
        slots = _stored(text, {"vehicle": (None, options), "when": ("January", ())})
        assert "vehicle" not in slots, text
        assert slots["when"]["value"] == "January"


def test_a_stated_choice_survives_an_idiom_in_the_same_slot():
    slots = _stored(
        "Thar or no Thar, we'll take the Jimny to Spiti.",
        {"vehicle": ("Jimny", ["Thar", "no Thar"])},
        certainty="confirmed",
    )
    assert slots["vehicle"] == {
        "value": "Jimny",
        "options": [],
        "certainty": "confirmed",
    }


def test_what_remains_after_an_idiom_is_never_promoted_to_a_decision():
    # "Jimny" was mentioned beside the idiom but not chosen: no decided value.
    slots = _stored(
        "Spiti, Thar or no Thar, maybe the Jimny.",
        {"vehicle": (None, ["Thar", "no Thar", "Jimny"])},
    )
    assert "vehicle" not in slots


def test_genuine_options_left_beside_an_idiom_stay_undecided():
    slots = _stored(
        "Ladakh or winter Spiti, Thar or no Thar, Jimny or Gypsy.",
        {
            "destination": (None, ["Ladakh", "winter Spiti"]),
            "vehicle": (None, ["Thar", "no Thar", "Jimny", "Gypsy"]),
        },
    )
    assert slots["destination"]["options"] == ["Ladakh", "winter Spiti"]
    assert slots["vehicle"] == {
        "value": None,
        "options": ["Jimny", "Gypsy"],
        "certainty": "tentative",
    }


def test_options_the_owner_never_said_are_still_refused():
    source, candidate = _say(
        "We're going to Spiti in January, Thar or no Thar.",
        {"vehicle": (None, ["Thar", "Jimny"])},
    )
    assert LearningPolicy().evaluate(source, candidate).reason == "unsupported_detail"


def test_an_idiom_never_decides_a_stored_choice():
    stored = {
        "schema": None,
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
            },
        },
    }
    from jarvis.authority.personal_learning import POLICY_VERSION

    stored["schema"] = POLICY_VERSION
    entry = _entry(stored)
    source, candidate = _say(
        "Spiti trip, Thar or no Thar.", {"vehicle": (None, ["Thar", "no Thar"])}
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
    for mutation in plan.mutations:
        assert mutation.draft.value["slots"]["vehicle"]["options"] == ["Thar", "Jimny"]
        assert mutation.draft.value["slots"]["vehicle"]["value"] is None
