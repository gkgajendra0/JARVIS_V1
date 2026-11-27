"""An answered question supplies identity, never evidence for an unsaid choice."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.memory.learning_clarification import (
    LearningClarification,
    ground_chosen_plan,
)
from jarvis.memory.learning_contracts import LearningCandidate


@pytest.mark.parametrize(
    "blocked",
    [
        "none",
        "no_answer",
        "unbound",
        "other_session",
        "old_words_missing",
        "latest_words_missing",
        "unsaid_choice",
        "tentative",
        "grounded_other_name",
        "two_plans",
        "unclear_question",
    ],
)
def test_identity_repair_requires_question_and_both_owner_turns(blocked):
    steps = json.loads(
        (Path(__file__).parent / "fixtures/codex_7b580710_d28.json").read_text(
            encoding="utf-8"
        )
    )["steps"]
    original = LearningCandidate.model_validate(
        steps["alt-01"]["extraction"]["candidates"][0]
    )
    original = original.model_copy(update={"label": original.value})
    candidate = LearningCandidate.model_validate(
        steps["alt-02"]["extraction"]["candidates"][0]
    )
    turns = [
        SimpleNamespace(
            turn_id=original.evidence[0].turn_id, text=steps["alt-01"]["utterance"]
        ),
        SimpleNamespace(
            turn_id=candidate.evidence[-1].turn_id, text=steps["alt-02"]["utterance"]
        ),
    ]
    source = SimpleNamespace(session_id="s1", turn_id=turns[-1].turn_id, turns=turns)
    note = LearningClarification(
        "s1",
        turns[0].turn_id,
        "plan",
        original.label,
        ("vehicle",),
        ("Thar", "Jimny"),
        kind="confirm_alternatives",
        choices=(("vehicle", ("Thar", "Jimny")),),
        candidate=original,
        plan_predicate="plan.other.trip",
    )
    notes = [note]
    if blocked == "no_answer":
        notes = []
    elif blocked == "unbound":
        notes = [replace(note, plan_predicate=None)]
    elif blocked == "other_session":
        notes = [replace(note, session_id="s2")]
    elif blocked == "old_words_missing":
        source.turns = turns[1:]
    elif blocked == "latest_words_missing":
        candidate = candidate.model_copy(update={"evidence": candidate.evidence[:1]})
    elif blocked in {"unsaid_choice", "tentative"}:
        slot = candidate.slots.vehicle.model_copy(
            update={
                "value": "Thar" if blocked == "unsaid_choice" else "Jimny",
                "certainty": "tentative" if blocked == "tentative" else "confirmed",
            }
        )
        candidate = candidate.model_copy(
            update={"slots": candidate.slots.model_copy(update={"vehicle": slot})}
        )
    elif blocked == "grounded_other_name":
        candidate = candidate.model_copy(
            update={"label": "January", "value": "January"}
        )
    elif blocked == "two_plans":
        notes += [replace(note, plan_predicate="plan.other.another")]
    elif blocked == "unclear_question":
        notes = [replace(note, kind="unclear")]
    repaired, bound = ground_chosen_plan(source, candidate, notes)
    if blocked == "none":
        assert repaired.label == original.label and repaired.value == original.value
        assert bound == (note,)
        assert repaired.slots == candidate.slots
    else:
        assert repaired is candidate and bound == ()
