import asyncio
import json
import sqlite3
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from jarvis.authority.conversation_history import ConversationHistoryAuthority
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.project_access import ProjectArchiveAccess
from jarvis.memory.project_context import build_project_context
from jarvis.memory.project_conversation_recording import (
    RecordingRoute,
    RequiredConversationRecorder,
)
from jarvis.memory.project_conversation_store import ProjectConversationStore
from jarvis.memory.project_conversations import ProjectSelection
from jarvis.memory.worker import SerialConnectionWorker

FIXTURES = Path(__file__).parent / "fixtures"


def test_200_original_events_across_10_projects_and_30_segments_reopen_exactly(
    tmp_path, authority_parts
):
    async def scenario():
        path = tmp_path / "replay.db"

        def connect():
            conn = sqlite3.connect(path)
            conn.execute("PRAGMA foreign_keys=ON")
            MemoryMigrationRunner().apply(conn)
            return conn

        writer = SerialConnectionWorker(connect, thread_name="replay-write")
        reader = SerialConnectionWorker(connect, thread_name="replay-read")
        issuer = ConversationHistoryAuthority(authority_parts.broker)
        grant = issuer.open("replay", "gemini")
        store = ProjectConversationStore(writer=writer, reader=reader, authority=issuer)
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        recorder = RequiredConversationRecorder(
            store, authority=issuer, grant=grant, source_clearance=lambda _: True
        )
        events = json.loads((FIXTURES / "events-v1.json").read_text(encoding="utf-8"))
        segments = {}
        receipts = []
        durations = []
        context_durations = []
        try:
            for p in range(10):
                await access.create_project(
                    ProjectSelection(f"p{p}", f"t{p}", 0), f"Project {p}"
                )
            for value in events:
                selection = ProjectSelection(value["project_id"], value["thread_id"], 0)
                if value["segment_id"] not in segments:
                    c = ConversationSession(session_id=value["segment_id"])
                    c.start()
                    segments[value["segment_id"]] = c
                c = segments[value["segment_id"]]
                raw = c.accept_turn(ConversationRole(value["role"]), value["text"])
                turn = replace(
                    raw,
                    turn_id=value["event_id"],
                    accepted_at=datetime.fromisoformat(value["accepted_at"]),
                )
                c._turns[-1] = turn
                revision = sum(r.thread_id == selection.thread_id for r in receipts)
                route = RecordingRoute(selection, revision, value["request_id"])
                started = time.perf_counter()
                receipt = await recorder.record(c, turn, route)
                durations.append((time.perf_counter() - started) * 1000)
                receipts.append(receipt)
                duplicate = await recorder.record(c, turn, route)
                assert (
                    duplicate.event_id == receipt.event_id
                    and duplicate.sequence == receipt.sequence
                )
            assert len(receipts) == 200 and len(segments) == 30
            for p in range(10):
                started = time.perf_counter()
                snapshot = await access.snapshot(ProjectSelection(f"p{p}", f"t{p}", 0))
                _, source_ids, estimate = build_project_context(snapshot)
                context_durations.append((time.perf_counter() - started) * 1000)
                assert estimate <= 6000 and all(
                    s.startswith(f"p{p}-") for s in source_ids
                )
        finally:
            await reader.close()
            await writer.close()
        with sqlite3.connect(path) as conn:
            stored = conn.execute(
                "SELECT event_id,thread_id,text,segment_id FROM conversation_event"
            ).fetchall()
            assert len(stored) == 200
            assert {r[0]: (r[1], r[2], r[3]) for r in stored} == {
                e["event_id"]: (e["thread_id"], e["text"], e["segment_id"])
                for e in events
            }
            assert conn.execute(
                "SELECT count(*) FROM conversation_workspace"
            ).fetchone() == (10,)
        report = {
            "events": 200,
            "projects": 10,
            "segments": 30,
            "committed": len(receipts),
            "duplicate_callbacks": 200,
            "local_archive_p95_ms": sorted(durations)[int(len(durations) * 0.95) - 1],
            "platform": "Linux SQLite fixture with real authority and fake OS/Hello; not Windows acceptance",
            "model_requests": 0,
            "local_context_p95_ms": sorted(context_durations)[
                int(len(context_durations) * 0.95) - 1
            ],
            "context_samples": len(context_durations),
        }
        (tmp_path / "replay-report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report))

    asyncio.run(scenario())


def test_model_questions_are_frozen_source_labelled_and_not_reported_as_inference():
    import hashlib

    events = json.loads((FIXTURES / "events-v1.json").read_text(encoding="utf-8"))
    questions = json.loads((FIXTURES / "questions-v1.json").read_text(encoding="utf-8"))
    ids = {e["event_id"] for e in events}
    assert len(questions) == 100
    assert sum(q["split"] == "development" for q in questions) == 60
    assert sum(q["split"] == "held_out" for q in questions) == 40
    assert all(set(q["source_ids"]) <= ids for q in questions)
    assert all(
        all(source.split("-")[0] == q["project_id"] for source in q["source_ids"])
        for q in questions
    )
    assert (
        hashlib.sha256(
            (FIXTURES / "questions-v1.json").read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest()
        == "0ea667daadbf7de34c409598e6a7e62355fe53f1896d0533f867c03a6fedf7a0"
    )
