"""The recorder graded against the real 2026-11-08 live run.

``data/live_run_20261108_timeline.json`` is the timeline read_timeline built
from the owner's production log (run start 05:53:13Z): transcripts, replies,
receipts, turn and session IDs. Three recorder defects showed on it:

- speech-to-text wrote "chimney" for "Jimny", so the vehicle step bound to
  the later correction turn; the forward search then bound the hotel step to
  the forget command and PASSED both wrong turns, skipping ten steps;
- "are we going to Pokhara or not?" lacked the word "decided" and its reply
  ("hasn't been decided") lacked "not";
- the project title kept the spoken capitalisation ("Interview Prep") and
  was compared exactly with "Interview prep".
"""

import json
from pathlib import Path

from jarvis.voice import project_memory_production_acceptance as a

DATA = Path(__file__).parent / "data" / "live_run_20261108_timeline.json"


def timeline():
    return [a.Turn(**item) for item in json.loads(DATA.read_text(encoding="utf-8"))]


def by_step(record):
    return {s["step_id"]: s for s in record["steps"]}


def test_every_step_binds_to_the_turn_that_was_actually_spoken():
    steps = by_step(a.grade(timeline(), None))
    expect = {
        "1-create": "Create a project called Nepal trip.",
        "1-fact-vehicle": "Okay, and we will take the chimney on our Nepal trip.",
        "1-fact-hotel": "Our hotel is Yak and Yeti.",
        "1-fact-tentative": "And maybe we will visit Pokhara. Not not decided yet.",
        "3-correct": "Okay. There is a correction. We will take Thar, not Jimny.",
        "4-create-second": "Create a project called Interview Prep.",
        "4-isolation": "Which hotel are we staying at?",
        "5-forget": "Okay. Now forget the Yak and Yeti Hotel.",
        "6-restart-tentative": "Now tell me, are we going to Pokhara or not?",
    }
    for step_id, said in expect.items():
        assert steps[step_id]["transcript"] == said, step_id


def test_the_live_run_grades_as_observed():
    steps = by_step(a.grade(timeline(), None))
    assert steps["4-isolation"]["verdict"] == "FAIL"  # the Yak and Yeti answer
    assert "reply contains 'yak'" in steps["4-isolation"]["reasons"]
    assert steps["5-recall-forgotten"]["verdict"] == "NOT TESTED"  # never asked
    for step_id in ("2-recall", "3-recall-corrected", "6-restart-tentative"):
        assert steps[step_id]["verdict"] == "PASS", steps[step_id]
    # The stray "project" turn had its reply dropped as internal text, so the
    # next statement's reply cannot be attributed with certainty: fail closed.
    assert steps["1-fact-vehicle"]["verdict"] == "FAIL"


def test_project_titles_compare_without_case():
    turns = timeline()
    rows = {}
    current = None
    for t in turns:
        text = t.user.casefold()
        if "nepal trip" in text and ("create" in text or "switch" in text):
            current = "Nepal trip"
        if "interview prep" in text and ("create" in text or "switch" in text):
            current = "Interview Prep"  # as spoken and stored
        rows[t.turn_id] = {"project": current, "text": t.user}
    db = {
        "present": {"Interview prep: Friday": 1},
        "absent": {},
        "duplicate_titles": [],
        "active_plan_labels": [],
        "run_plan_labels": [],
        "turns": rows,
    }
    steps = by_step(a.grade(turns, db))
    for step_id in ("4-create-second", "4-fact", "6-restart-other"):
        assert (
            "canonical turn missing from expected project"
            not in steps[step_id]["reasons"]
        ), step_id
