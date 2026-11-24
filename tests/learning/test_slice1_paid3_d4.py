"""Paid lab 3 (5e2ce9c7) D4, reproduced from the recorded request and result
(fixtures/paid3_d4_recorded.json).

"Should I service my bike before the trip?" with two saved bikes and one
saved trip. The model asked for vehicles with target_quote "bike" and plans
with "trip". "bike" is no item's name and "trip" is a plan head noun, so both
quotes matched nothing; the tool said no_match and its absence rule read
no_match as "nothing is saved in that category", and the answer claimed
nothing was saved.

General fixes: (1) a quote made only of the category's own words (articles,
"bike", "car", "trip", "plan", ...) names no item and does not narrow the
category: every item is listed, marked generic, and several items must be
clarified; (2) a quote that names no saved item in a non-empty category is
"no_named_match", never absence.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_context_projection import record

from jarvis.memory.personal_context_projection import (
    ScopedContextSnapshot,
    parse_context_requests,
    project_personal_context,
)
from jarvis.voice.personal_context import annotate_lookup

D4 = json.loads(
    (Path(__file__).parent / "fixtures" / "paid3_d4_recorded.json").read_text(
        encoding="utf-8"
    )
)


def _item(label, ident, scope):
    r = record(label, ident)
    if scope == "plan":
        return replace(
            r,
            value={**r.value, "category": "plan", "kind": "other", "state": "planned"},
            predicate="plan_" + ident,
        )
    return r


def _snapshot(labels=None):
    labels = labels if labels is not None else D4["stored_labels"]
    return ScopedContextSnapshot(
        tuple(
            (_item(label, f"{scope}-{i}", scope), scope)
            for scope, names in labels.items()
            for i, label in enumerate(names)
        ),
        (),
    )


def _lookup(requests, question=D4["utterance"], labels=None):
    return project_personal_context(
        _snapshot(labels), parse_context_requests(requests, question=question)
    )


def _texts(result):
    return sorted(f["text"] for f in result.facts)


def test_recorded_d4_request_now_lists_both_bikes_and_the_trip():
    assert D4["result"]["status"] == "no_match"  # Paid lab 3
    result = _lookup(D4["requests"])
    assert result.status == "selected"
    assert _texts(result) == ["Classic 350", "Pulsar 150", "Spiti trip in January"]
    assert result.generic_targets == ("owned_item.vehicle", "plan")
    assert dict(result.scope_results) == {
        "owned_item.vehicle": "selected",
        "plan": "selected",
    }


def test_the_reply_is_told_the_quote_was_generic_and_to_ask_which_one():
    from jarvis.voice.personal_context import GENERIC_TARGET_NOTE

    assert "ask which one" in GENERIC_TARGET_NOTE


@pytest.mark.parametrize(
    "quote,question,expected",
    [
        ("Pulsar", "Should I service my Pulsar?", ["Pulsar 150"]),
        ("my Pulsar bike", "Should I service my Pulsar bike?", ["Pulsar 150"]),
        ("Classic", "Is the Classic due?", ["Classic 350"]),
    ],
)
def test_a_name_still_narrows_to_that_item(quote, question, expected):
    result = _lookup(
        [{"scope_key": "owned_item.vehicle", "target_quote": quote}], question
    )
    assert _texts(result) == expected
    assert result.generic_targets == ()


def test_a_generic_quote_never_picks_one_of_several_items():
    # Ambiguity is kept: both bikes are listed, neither is chosen.
    result = _lookup(
        [{"scope_key": "owned_item.vehicle", "target_quote": "the bike"}],
        "Should I service the bike?",
    )
    assert _texts(result) == ["Classic 350", "Pulsar 150"]
    one = _lookup(
        [{"scope_key": "owned_item.vehicle", "target_quote": "bike"}],
        labels={"owned_item.vehicle": ["Pulsar 150"]},
    )
    assert _texts(one) == ["Pulsar 150"]


def test_a_shared_name_word_still_asks_which_one():
    result = _lookup(
        [{"scope_key": "owned_item.vehicle", "target_quote": "350"}],
        "Is the 350 due?",
        labels={"owned_item.vehicle": ["Classic 350", "Meteor 350"]},
    )
    assert result.status == "clarification_required"
    assert result.reason == "ambiguous_target" and result.facts == ()


def test_a_generic_quote_never_leaves_its_requested_scope():
    result = _lookup([{"scope_key": "owned_item.vehicle", "target_quote": "bike"}])
    assert _texts(result) == ["Classic 350", "Pulsar 150"]  # no plan


def test_category_words_are_only_ignored_for_their_own_category():
    # "bike" is a vehicle word, not a plan word: in the plan scope it is a
    # name word and matches a plan named with it.
    labels = {"plan": ["Spiti bike ride", "Goa trip"]}
    result = _lookup(
        [{"scope_key": "plan", "target_quote": "bike"}],
        "When is the bike ride?",
        labels=labels,
    )
    assert _texts(result) == ["Spiti bike ride"]


def test_a_name_that_matches_nothing_is_not_reported_as_absence():
    result = _lookup(
        [{"scope_key": "owned_item.vehicle", "target_quote": "Nexon"}],
        "When did I buy the Nexon?",
    )
    assert result.status == "no_match" and result.facts == ()
    assert dict(result.scope_results) == {"owned_item.vehicle": "no_named_match"}
    annotated = annotate_lookup(
        {"status": result.status, "facts": [], "scopes": dict(result.scope_results)},
        [{"scope_key": "owned_item.vehicle", "target_quote": "Nexon"}],
    )
    assert annotated["scopes"] == {"owned_item.vehicle": "no_named_match"}
    assert "not absence" in annotated["named_miss_rule"]


def test_an_empty_category_is_still_plain_absence():
    result = _lookup(
        [{"scope_key": "owned_item.vehicle", "target_quote": "bike"}],
        labels={"plan": ["Goa trip"]},
    )
    assert result.status == "no_match"
    assert dict(result.scope_results) == {"owned_item.vehicle": "no_match"}
    annotated = annotate_lookup(
        {"status": "no_match", "facts": [], "scopes": dict(result.scope_results)},
        [{"scope_key": "owned_item.vehicle", "target_quote": "bike"}],
    )
    assert "named_miss_rule" not in annotated


def test_the_answer_instructions_forbid_reading_a_named_miss_as_absence():
    from jarvis.voice.agent import PERSONAL_LEARNING_QUERY_INSTRUCTIONS as text

    flat = " ".join(text.split())
    assert "no_named_match" in flat and "it is not absence" in flat
    assert "name them and ask" in flat
