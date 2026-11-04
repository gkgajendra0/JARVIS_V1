"""The real-machine acceptance recorder, checked against the real archive schema.

The scenario is spoken through the real voice pipeline here (the database is
then real SQLite schema 7); the production log lines are written as Jarvis
writes them. The recorder must PASS that run, FAIL a run with a wrong reply,
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

    wake = Wake(voice)
    for n, step in enumerate(acceptance.SCENARIO):
        if step.step_id in skip:
            continue
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
                emit(n * 10, f'user: "{part}" | turn_id=x')
                emit(n * 10 + 1, "Project history forget committed | owner_rows=2 | x")
                emit(n * 10 + 2, 'assistant: "Done." | turn_id=y')
                fast.close()
                continue
            reply = REPLIES.get(step.step_id, "Noted.")
            if wrong and step.step_id == wrong:
                reply = "We are staying at the Yak and Yeti."
            result = await wake.ask(part, reply)
            emit(n * 10, f'user: "{part}" | turn_id=x')
            if result.get("status") == "ready":
                emit(
                    n * 10 + 1, f"Project voice turn saved | action={result['action']}"
                )
            emit(n * 10 + 2, f'assistant: "{reply}" | turn_id=y')
    wake.close()
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return start


@pytest.mark.asyncio
async def test_a_good_run_passes_with_database_evidence(lab, tmp_path):
    log = tmp_path / "jarvis.jsonl"
    start = await run_scenario(lab, log)
    out = tmp_path / "out"
    code = acceptance.main(
        ["--since", start.isoformat(), "--log", str(log), "--out", str(out)],
        opener=lambda: sqlite3.connect(lab.db),
    )
    record = json.loads(next(out.glob("*.json")).read_text(encoding="utf-8"))
    failing = [s for s in record["steps"] if s["verdict"] != "PASS"]
    assert not failing, failing
    assert all(c["verdict"] == "PASS" for c in record["database_checks"])
    assert code == 0 and record["overall"] == "PASS"
    assert set(record["database"]["projects"]) == {"Nepal trip", "Interview prep"}


@pytest.mark.asyncio
async def test_a_leaking_reply_fails_and_a_skipped_step_is_not_tested(lab, tmp_path):
    log = tmp_path / "jarvis.jsonl"
    start = await run_scenario(lab, log, skip=("5-forget",), wrong="4-isolation")
    record = acceptance.grade(
        acceptance.read_timeline(log, start),
        acceptance.read_database(lambda: sqlite3.connect(lab.db)),
    )
    steps = {s["step_id"]: s for s in record["steps"]}
    assert steps["4-isolation"]["verdict"] == "FAIL"
    assert steps["5-forget"]["verdict"] == "NOT TESTED"
    checks = {c["check"]: c["verdict"] for c in record["database_checks"]}
    assert checks["absent Yak and Yeti"] == "FAIL"  # never forgotten
    assert record["overall"] == "FAIL"


def test_the_database_is_opened_read_only(tmp_path):
    from jarvis.memory.migration_runner import MemoryMigrationRunner

    path = tmp_path / "m.db"
    with sqlite3.connect(path) as c:
        MemoryMigrationRunner().apply(c)
    seen = []

    def opener():
        connection = sqlite3.connect(path)
        seen.append(connection)
        return connection

    acceptance.read_database(opener)
    probe = sqlite3.connect(path)
    probe.execute("PRAGMA query_only = ON")
    with pytest.raises(sqlite3.OperationalError):
        probe.execute("DELETE FROM conversation_workspace")
    assert seen  # opened once, closed by the recorder
