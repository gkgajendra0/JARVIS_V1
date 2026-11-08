"""The real-machine acceptance recorder, checked against the real archive schema.

The scenario is spoken through the real voice pipeline here (the database is
then real SQLite schema 7); the production log lines are written as Jarvis
writes them. The recorder must collect that run without certifying semantic correctness,
FAIL a run with a wrong reply,
a missing receipt or a fact left behind, and say NOT TESTED for skipped steps.
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from test_project_voice import Wake
from test_project_voice import lab as voice_lab
from test_project_voice_fast_path import FastWake
from test_project_voice_forget_recall import ask_to_forget

from jarvis.voice import project_memory_production_acceptance as acceptance

lab = voice_lab

REPLIES = {
    "1-create": "Created project Nepal trip.",
    "2-recall": "We are taking the Jimny; Pokhara is not decided.",
    "3-recall-corrected": "The Thar.",
    "4-create-second": "Created project Interview prep.",
    "4-isolation": "I don't know which hotel.",
    "4-cross-project": "In your Nepal trip project, the hotel is Yak and Yeti.",
    "5-switch": "Switched to Nepal trip.",
    "5-recall-forgotten": "I don't have a hotel saved.",
    "6-restart-other": "Friday at ten.",
    "6-restart-tentative": "No, Pokhara is not decided yet.",
}


def _spoken(step):
    return step.say.split(") ", 1)[-1].split(" (approve")[0]


async def run_scenario(lab, log, *, skip=(), wrong=None):
    voice = await lab.runtime()
    start = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    lines = []

    def emit(seconds, event):
        lines.append(
            json.dumps(
                {
                    "event": event,
                    "timestamp": (start + timedelta(seconds=seconds)).isoformat(),
                }
            )
        )

    def identity(wake):
        user = next(
            t for t in reversed(wake.conversation.turns) if t.role.value == "user"
        )
        return f"turn_id={user.turn_id} | session_id={wake.conversation.session_id}"

    def transcript(wake, part):
        user = next(
            t for t in reversed(wake.conversation.turns) if t.role.value == "user"
        )
        return f'user: "{part}" | turn_id={user.turn_id} | session_id={wake.conversation.session_id}'

    wake = Wake(voice)
    for n, step in enumerate(acceptance.SCENARIO):
        if step.step_id in skip:
            continue
        if step.step_id in acceptance.NEW_WAKE_STEPS:
            wake.close()
            wake = Wake(voice)
        said = _spoken(step)
        for part in said.split(". ") if step.step_id.startswith("6-") else [said]:
            if step.step_id == "6-restart-other" and part.startswith("Switch"):
                await voice.aclose()
                voice = await lab.runtime()
                wake = Wake(voice)
            if step.forget:
                fast = FastWake(voice)
                await fast.preload()
                result = await ask_to_forget(fast, part, "Yak Yeti")
                assert result["status"] == "forgotten", result
                emit(n * 10, transcript(fast, part))
                emit(
                    n * 10 + 1,
                    "Project history forget committed | owner_rows=2 | "
                    + identity(fast),
                )
                emit(
                    n * 10 + 2,
                    f'assistant: "Done." | turn_id=y | session_id={fast.conversation.session_id}',
                )
                fast.close()
                continue
            reply = REPLIES.get(step.step_id, "Noted.")
            if wrong and step.step_id == wrong:
                reply = "We are staying at the Yak and Yeti."
            result = await wake.ask(part, reply)
            emit(n * 10, transcript(wake, part))
            if result.get("status") == "ready":
                emit(
                    n * 10 + 1,
                    f"Project voice turn saved | action={result['action']} | "
                    + identity(wake),
                )
            emit(
                n * 10 + 2,
                f'assistant: "{reply}" | turn_id=y | session_id={wake.conversation.session_id}',
            )
    wake.close()
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return start


@pytest.mark.asyncio
async def test_a_good_automated_run_still_requires_explicit_review(lab, tmp_path):
    log = tmp_path / "jarvis.jsonl"
    start = await run_scenario(lab, log)
    out = tmp_path / "out"
    code = acceptance.main(
        ["--since", start.isoformat(), "--log", str(log), "--out", str(out)],
        opener=lambda: sqlite3.connect(lab.db),
    )
    record = json.loads(
        next(
            p for p in out.glob("*.json") if not p.name.endswith(".review.json")
        ).read_text(encoding="utf-8")
    )
    failing = [s for s in record["steps"] if s["verdict"] != "PASS"]
    assert not failing, failing
    assert all(c["verdict"] == "PASS" for c in record["database_checks"])
    assert code == 1 and record["overall"] == "INCOMPLETE"
    assert next(out.glob("*.review.json")).exists()
    assert set(record["database"]["projects"]) == {"Nepal trip", "Interview prep"}

    # CLI round-trip: collecting evidence never approves it. Only a completed
    # review bound to those exact synthetic observations may produce PASS.
    review_path = next(out.glob("*.review.json"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["reviewer"] = "Synthetic acceptance observer"
    for item in review["checks"].values():
        item.update(verdict="PASS", evidence="Observed in this synthetic fixture only.")
    review_path.write_text(json.dumps(review), encoding="utf-8")
    assert (
        acceptance.main(
            [
                "--since",
                start.isoformat(),
                "--log",
                str(log),
                "--out",
                str(out),
                "--review",
                str(review_path),
            ],
            opener=lambda: sqlite3.connect(lab.db),
        )
        == 0
    )


@pytest.mark.asyncio
async def test_a_leaking_reply_fails_and_a_skipped_step_is_not_tested(lab, tmp_path):
    log = tmp_path / "jarvis.jsonl"
    start = await run_scenario(lab, log, skip=("5-forget",), wrong="4-isolation")
    record = acceptance.grade(
        acceptance.read_timeline(log, start),
        acceptance.read_database(
            lambda: sqlite3.connect(lab.db),
            turn_ids=[t.turn_id for t in acceptance.read_timeline(log, start)],
        ),
    )
    steps = {s["step_id"]: s for s in record["steps"]}
    assert steps["4-isolation"]["verdict"] == "FAIL"
    assert steps["5-forget"]["verdict"] == "NOT TESTED"
    checks = {c["check"]: c["verdict"] for c in record["database_checks"]}
    assert checks["absent Yak and Yeti"] == "FAIL"  # never forgotten
    assert record["overall"] == "FAIL"


def test_recorder_uses_query_only_on_the_connection_it_actually_reads(tmp_path):
    from jarvis.memory.migration_runner import MemoryMigrationRunner

    path = tmp_path / "m.db"
    with sqlite3.connect(path) as c:
        MemoryMigrationRunner().apply(c)
    seen = []

    class InspectConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith("SELECT"):
                assert super().execute("PRAGMA query_only").fetchone()[0] == 1
                with pytest.raises(sqlite3.OperationalError):
                    super().execute("DELETE FROM conversation_workspace")
                seen.append(sql)
            return super().execute(sql, parameters)

    acceptance.read_database(lambda: sqlite3.connect(path, factory=InspectConnection))
    assert seen


@pytest.mark.asyncio
async def test_real_runtime_save_receipt_survives_interleaved_log_order(
    lab, tmp_path, caplog
):
    import logging

    voice = await lab.runtime()
    wake = Wake(voice)
    with caplog.at_level(logging.INFO, logger="jarvis.voice.project_voice"):
        await wake.ask("Create a project called Nepal trip", "Created.")
    user = next(t for t in wake.conversation.turns if t.role.value == "user")
    events = [
        f'user: "{user.text}" | turn_id={user.turn_id} | session_id={wake.conversation.session_id}',
        'user: "A later wake" | turn_id=later | session_id=other',
    ]
    events.extend(r.getMessage() for r in caplog.records)
    log = tmp_path / "actual-receipts.jsonl"
    log.write_text(
        "\n".join(
            json.dumps({"event": e, "timestamp": "2026-11-04T14:00:00Z"})
            for e in events
        ),
        encoding="utf-8",
    )
    turns = acceptance.read_timeline(log, datetime(2026, 11, 4, tzinfo=UTC))
    assert turns[0].saved_action == "created"
    assert turns[1].saved_action is None
    wake.close()


def test_transcripts_are_decoded_exactly_as_livekit_logs_them(tmp_path):
    # livekit_session logs json.dumps(text, ensure_ascii=False); the recorder
    # compares the decoded text with the stored canonical turn.
    said = 'Path C:\\trips "Nepal"\nनेपाल'
    logged = json.dumps(said, ensure_ascii=False)
    event = f"user: {logged} | turn_id=t1 | session_id=s1"
    log = tmp_path / "jarvis.jsonl"
    log.write_text(
        json.dumps({"event": event, "timestamp": "2026-11-05T10:00:00+00:00"}) + "\n",
        encoding="utf-8",
    )
    (turn,) = acceptance.read_timeline(log, datetime(2026, 11, 5, tzinfo=UTC))
    assert turn.user == said


@pytest.mark.asyncio
async def test_database_facts_match_titles_in_any_capitalisation(lab):
    # 2026-11-08: the title was stored as spoken, "Interview Prep".
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask(
        "Create a project called Interview Prep.", "Created project Interview Prep."
    )
    await wake.ask("The interview panel is on Friday at 10:00.", "Understood.")
    wake.close()
    db = acceptance.read_database(lambda: sqlite3.connect(lab.db))
    assert "Interview Prep" in db["projects"]
    assert db["present"]["Interview prep: Friday"] == 1
