"""Acceptance must not turn incomplete or unrelated evidence into a release PASS."""

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from jarvis.voice import project_memory_production_acceptance as a


def evidence():
    replies = {
        "2-recall": "The Jimny; Pokhara is not decided.",
        "3-recall-corrected": "The Thar.",
        "4-isolation": "I do not know the hotel.",
        "5-recall-forgotten": "I do not have a hotel saved.",
        "6-restart-other": "Friday at ten.",
        "6-restart-tentative": "No, it is not decided.",
    }
    turns = []
    rows = {}
    for n, step in enumerate(a.SCENARIO):
        turn = a.Turn(
            datetime(2026, 11, 4, 14, n, tzinfo=UTC).isoformat(),
            step.say,
            replies.get(step.step_id, "Nepal trip; Interview prep; noted."),
            step.action or "continued",
            2 if step.forget else None,
        )
        turn.turn_id = f"turn-{n}"
        turn.session_id = f"wake-{n}"
        turns.append(turn)
        title = (
            "Interview prep"
            if step.step_id.startswith("4-") or step.step_id == "6-restart-other"
            else "Nepal trip"
        )
        if step.step_id not in {"1-fact-hotel", "5-forget"}:
            rows[turn.turn_id] = {"project": title, "text": turn.user}
    db = {
        "projects": {},
        "present": {"Nepal trip: Thar": 1},
        "absent": {"Yeti": 0},
        "duplicate_titles": [],
        "active_plan_labels": [],
        "turns": rows,
    }
    return turns, db


def test_automated_evidence_alone_cannot_certify_model_meaning_or_restart():
    turns, db = evidence()
    assert a.grade(turns, db)["overall"] == "INCOMPLETE"


def test_missing_save_receipt_fails_a_fact_step():
    turns, db = evidence()
    turns[1].saved_action = None
    result = a.grade(turns, db)
    assert result["steps"][1]["verdict"] == "FAIL"


def test_silence_is_not_successful_isolation():
    turns, db = evidence()
    turns[9].reply = ""
    assert a.grade(turns, db)["steps"][9]["verdict"] == "FAIL"


def test_existing_questionable_plan_requires_review_instead_of_pass():
    turns, db = evidence()
    db["active_plan_labels"] = ["Nepal trip"]
    assert a.grade(turns, db)["overall"] == "INCOMPLETE"


def test_old_or_wrong_project_rows_cannot_prove_this_turn_was_saved():
    turns, db = evidence()
    db["turns"][turns[1].turn_id]["project"] = "Interview prep"
    assert a.grade(turns, db)["steps"][1]["verdict"] == "FAIL"


def test_recall_in_the_same_wake_fails_new_wake_requirement():
    turns, db = evidence()
    turns[4].session_id = turns[3].session_id
    assert a.grade(turns, db)["steps"][4]["verdict"] == "FAIL"


def test_exact_duplicate_titles_are_detected_before_dictionary_collapses_them(tmp_path):
    from jarvis.memory.migration_runner import MemoryMigrationRunner

    path = tmp_path / "archive.db"
    with sqlite3.connect(path) as c:
        MemoryMigrationRunner().apply(c)
        c.executemany(
            "INSERT INTO conversation_workspace(project_id,title) VALUES (?,?)",
            [("p1", "Nepal trip"), ("p2", "Nepal trip")],
        )
    result = a.read_database(lambda: sqlite3.connect(path))
    assert result["duplicate_titles"] == ["Nepal trip"]


def completed_review(turns, db):
    record = a.grade(turns, db)
    review = a.review_template(record)
    review["reviewer"] = "Acceptance observer"
    for item in review["checks"].values():
        item.update(
            verdict="PASS",
            evidence="Reviewed the recorded reply and observed the required action.",
        )
    return review


def test_completed_evidence_bound_review_can_pass():
    turns, db = evidence()
    review = completed_review(turns, db)
    assert a.grade(turns, db, review=review)["overall"] == "PASS"


def test_changed_reply_invalidates_an_earlier_review():
    turns, db = evidence()
    review = completed_review(turns, db)
    turns[6].reply = "The Thar and Jimny are both confirmed."
    assert a.grade(turns, db, review=review)["overall"] == "INCOMPLETE"


def test_review_cannot_override_failed_database_evidence():
    turns, db = evidence()
    db["turns"].pop(turns[1].turn_id)
    review = completed_review(turns, db)
    assert a.grade(turns, db, review=review)["overall"] == "FAIL"


def test_unobserved_restart_and_rejected_answer_block_release():
    turns, db = evidence()
    review = completed_review(turns, db)
    review["checks"]["observed-restart"] = {"verdict": "PASS", "evidence": ""}
    assert a.grade(turns, db, review=review)["overall"] == "INCOMPLETE"
    review["checks"]["3-recall-corrected"] = {
        "verdict": "FAIL",
        "evidence": "Still asserts the old vehicle.",
    }
    assert a.grade(turns, db, review=review)["overall"] == "FAIL"


@pytest.mark.parametrize("identity", [None, False, 0, [], {}])
def test_review_requires_a_real_nonempty_name(identity):
    turns, db = evidence()
    review = completed_review(turns, db)
    review["reviewer"] = identity
    assert a.grade(turns, db, review=review)["overall"] == "INCOMPLETE"


def test_final_record_identifies_the_reviewer():
    turns, db = evidence()
    result = a.grade(turns, db, review=completed_review(turns, db))
    assert result["reviewer"] == "Acceptance observer"


def timeline(tmp_path, events):
    path = tmp_path / "interleaved.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"timestamp": "2026-11-04T14:00:00Z", "event": e})
            for e in events
        ),
        encoding="utf-8",
    )
    return a.read_timeline(path, datetime(2026, 11, 4, tzinfo=UTC))


def test_delayed_old_wake_reply_and_receipt_stay_with_their_source(tmp_path):
    turns = timeline(
        tmp_path,
        [
            'user: "Create Nepal" | turn_id=a | session_id=old',
            'user: "Which vehicle?" | turn_id=b | session_id=new',
            'assistant: "The Jimny" | turn_id=c | session_id=old',
            "Project voice turn saved | action=created | turn_id=a | session_id=old",
        ],
    )
    assert turns[0].reply == "The Jimny"
    assert turns[0].saved_action == "created"
    assert turns[1].reply == "" and turns[1].saved_action is None


def test_legacy_unbound_receipts_cannot_supply_acceptance_evidence(tmp_path):
    turns = timeline(
        tmp_path,
        [
            'user: "Which vehicle?" | turn_id=a | session_id=w',
            "Project voice turn saved | action=continued",
        ],
    )
    assert turns[0].saved_action is None


def test_multiple_unanswered_users_in_one_wake_are_flagged_as_ambiguous(tmp_path):
    turns = timeline(
        tmp_path,
        [
            'user: "First" | turn_id=a | session_id=w',
            'user: "Second" | turn_id=b | session_id=w',
            'assistant: "An answer" | turn_id=c | session_id=w',
        ],
    )
    assert all(t.not_saved == "ambiguous_reply_attribution" for t in turns)


def test_a_plan_kept_from_before_the_run_does_not_block_acceptance():
    # The owner kept the 2026-11-04 "Nepal trip" plan fact. It predates the
    # run, so it is listed but cannot make the run INCOMPLETE; one learned
    # during the run still needs review.
    turns, db = evidence()
    db["active_plan_labels"] = ["Nepal trip"]
    db["run_plan_labels"] = []
    checks = {c["check"]: c["verdict"] for c in a.grade(turns, db)["database_checks"]}
    assert checks["no plan learned from a project command"] == "PASS"
    db["run_plan_labels"] = ["Nepal trip"]
    checks = {c["check"]: c["verdict"] for c in a.grade(turns, db)["database_checks"]}
    assert checks["no plan learned from a project command"] == "REVIEW"


def test_read_database_separates_plans_recorded_before_the_run(tmp_path):
    import json
    import sqlite3
    from datetime import UTC, datetime

    from jarvis.memory.migration_runner import MemoryMigrationRunner

    path = tmp_path / "m.db"
    c = sqlite3.connect(path)
    MemoryMigrationRunner().apply(c)
    c.execute("PRAGMA foreign_keys=OFF")
    for n, (label, at) in enumerate(
        [("Nepal trip", "2026-11-04T12:44:47Z"), ("Goa", "2026-11-08T10:00:00Z")]
    ):
        c.execute(
            "INSERT INTO semantic_assertion(assertion_id,subject_scope,subject,"
            "predicate,value_type,value_json,normalized_text,source_id,system_from,"
            "state,verification_state,freshness_class,sensitivity,created_at,"
            "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"a{n}", "owner", "owner", f"plan_{n}", "json",
                json.dumps({"label": label}), label, "s", at, "active", "unverified",
                "changeable", "standard", at, at,
            ),
        )  # fmt: skip
    c.commit()
    c.close()
    db = a.read_database(
        lambda: sqlite3.connect(path), since=datetime(2026, 11, 8, tzinfo=UTC)
    )
    assert sorted(db["active_plan_labels"]) == ["Goa", "Nepal trip"]
    assert db["run_plan_labels"] == ["Goa"]
