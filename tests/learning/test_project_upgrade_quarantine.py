"""Upgrading a database with an already-forgotten project is non-destructive.

Migration 0007 quarantines older, untracked Jarvis replies that may repeat a
forgotten project: they keep their text but are never used again until the
owner reviews them and approves deletion or restoration with Windows Hello.
"""

import sqlite3
from datetime import UTC, datetime

import pytest
from test_project_forget_provenance import FACT, EchoingModel, rows, say

from jarvis.authority.conversation_history import (
    ConversationHistoryAuthority,
    HistoryActionBinding,
)
from jarvis.memory.migration_runner import (
    MemoryMigrationRunner,
    discover_memory_migrations,
)
from jarvis.memory.project_access import ProjectArchiveAccess
from jarvis.memory.project_controls import ProjectControls
from jarvis.memory.project_conversation_store import (
    ProjectConversationStore,
    archive_digest,
)
from jarvis.memory.project_conversations import ConversationEvent, ProjectSelection
from jarvis.memory.worker import SerialConnectionWorker
from jarvis.voice.project_answer_provider import ProjectAnswerProvider
from jarvis.voice.project_conversation import ProjectConversationCoordinator

OMISSION = '{"capture":"omitted","reason":"retention_paused","source_role":"user"}'
EVENTS = [
    # Nepal reply saved before Interview preparation existed: never suspect.
    ("n1", "tn", 1, "user", "We will take the Jimny", "complete", "01:00"),
    ("n2", "tn", 2, "assistant", "Understood.", "complete", "01:01"),
    ("i1", "ti", 1, "tool", "[forgotten]", "failed", "02:00"),
    ("n3", "tn", 3, "user", "What is my interview topic?", "complete", "03:00"),
    (
        "n4",
        "tn",
        4,
        "assistant",
        f"Your interview topic is {FACT}.",
        "complete",
        "03:01",
    ),
    ("n5", "tn", 5, "tool", OMISSION, "failed", "03:02"),
    ("n6", "tn", 6, "assistant", f"It is {FACT}.", "complete", "05:00"),
    ("g1", "tg", 1, "assistant", "Groceries list noted.", "complete", "06:00"),
]


def legacy_database(path):
    """The owner's schema-6 lab after the faulty forget at c52c7018."""
    with sqlite3.connect(path) as connection:
        MemoryMigrationRunner(discover_memory_migrations()[:6]).apply(connection)
        connection.executescript(
            """
            INSERT INTO conversation_workspace(project_id,title) VALUES ('nepal','Nepal trip');
            INSERT INTO conversation_thread(thread_id,project_id,last_sequence,archive_revision)
                VALUES ('tn','nepal',6,6);
            INSERT INTO conversation_workspace(project_id,title) VALUES ('general','General');
            INSERT INTO conversation_thread(thread_id,project_id,last_sequence,archive_revision)
                VALUES ('tg','general',1,1);
            INSERT INTO conversation_workspace(project_id,title,epoch,forgotten_at)
                VALUES ('interview','[forgotten]',1,'2026-11-02T04:00:00+00:00');
            INSERT INTO conversation_thread(thread_id,project_id) VALUES ('ti','interview');
            INSERT INTO conversation_selection VALUES ('owner','nepal','tn',3);
            """
        )
        for event_id, thread, seq, role, text, delivery, at in EVENTS:
            digest = "0" * 64 if event_id == "i1" else "a" * 64
            connection.execute(
                "INSERT INTO conversation_event(event_id,thread_id,sequence,revision,segment_id,"
                "request_id,role,text,accepted_at,delivery,payload_sha256) VALUES "
                "(?,?,?,?,'s',?,?,?,?,?,?)",
                (
                    event_id,
                    thread,
                    seq,
                    seq,
                    f"r-{event_id}",
                    role,
                    text,
                    f"2026-11-02T{at}:00.000000+00:00",
                    delivery,
                    digest,
                ),
            )


async def open_lab(tmp_path, parts):
    path = tmp_path / "history.db"
    legacy_database(path)
    with sqlite3.connect(path) as connection:
        assert MemoryMigrationRunner().apply(connection) == 7
    writer = SerialConnectionWorker(lambda: sqlite3.connect(path), thread_name="w")
    reader = SerialConnectionWorker(lambda: sqlite3.connect(path), thread_name="r")
    issuer = ConversationHistoryAuthority(parts.broker)
    grant = issuer.open("runtime", "gemini")
    store = ProjectConversationStore(writer=writer, reader=reader, authority=issuer)
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    return path, access, ProjectControls(access), issuer, grant, writer, reader


def text_of(path, event_id):
    return rows(
        path, "SELECT text FROM conversation_event WHERE event_id=?", (event_id,)
    )[0][0]


@pytest.mark.asyncio
async def test_upgrade_quarantines_without_deleting_anything(tmp_path, authority_parts):
    path, access, controls, _, _, writer, reader = await open_lab(
        tmp_path, authority_parts
    )
    try:
        # No content changed during migration.
        for event_id, *_, text, _, _ in EVENTS:
            assert text_of(path, event_id) == text
        report = await controls.quarantine_report()
        assert report.count == 3
        assert report.projects == (("General", 1), ("Nepal trip", 2))
        quarantined = {
            r[0]
            for r in rows(path, "SELECT event_id FROM conversation_event_quarantine")
        }
        # Owner turns, the omission marker and the pre-Interview reply stay usable.
        assert quarantined == {"n4", "n6", "g1"}
        reviewed = await controls.inspect_quarantine()
        assert {r[3] for r in reviewed} == {
            f"Your interview topic is {FACT}.",
            f"It is {FACT}.",
            "Groceries list noted.",
        }
        nepal = ProjectSelection("nepal", "tn", 0)
        recent = await access.snapshot(nepal, project_wide=True)
        assert {s.event.event_id for s in recent.sources} == {"n1", "n2", "n3", "n5"}
        found = await access.snapshot(nepal, query="SQL window", all_projects=True)
        # "partial" only because of Nepal's omission marker; no source matches.
        assert found.sources == ()
        with pytest.raises(PermissionError):
            await access.snapshot(nepal, source_ids=("n4",), project_wide=True)
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_forgotten_fact_does_not_reappear_through_quarantined_replies(
    tmp_path, authority_parts
):
    _, access, _, _, _, writer, reader = await open_lab(tmp_path, authority_parts)
    model = EchoingModel()
    provider = ProjectAnswerProvider(model)
    coordinator = ProjectConversationCoordinator(
        access, source_clearance=lambda _: True
    )
    try:
        answer = await say(coordinator, provider, "What is my interview topic?")
        assert FACT not in answer.answer
        assert all(FACT not in str(c) for c in model.contexts)
        # A reply citing a quarantined message cannot be saved.
        event = ConversationEvent(
            "late",
            "s",
            "r-late",
            "assistant",
            "late reply",
            datetime(2026, 11, 2, 7, tzinfo=UTC),
            evidence=("n4",),
        )
        nepal = ProjectSelection("nepal", "tn", 0)
        snapshot = await access.snapshot(nepal)
        material = access.store.append_material(nepal, event, snapshot.archive_revision)
        access.authority.register_source(access.grant, event.event_id, source=event)
        permit = access.authority.issue_child(
            access.grant,
            HistoryActionBinding(
                "admit",
                event.event_id,
                archive_digest(material),
                targets=(("project", "nepal"), ("thread", "tn")),
            ),
        )
        with pytest.raises(PermissionError, match="forgotten or is missing"):
            await access.store.append_event(
                nepal, event, permit=permit, expected_revision=snapshot.archive_revision
            )
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_owner_approved_delete_tombstones_only_the_quarantine(
    tmp_path, authority_parts
):
    path, _, controls, _, _, writer, reader = await open_lab(tmp_path, authority_parts)
    try:
        before = len(authority_parts.hello.calls)
        report = await controls.resolve_quarantine("delete")
        assert report.count == 3
        assert len(authority_parts.hello.calls) == before + 1
        summary = authority_parts.hello.calls[-1].material_summary
        assert "Permanently delete 3" in summary and "Nepal trip (2)" in summary
        for event_id in ("n4", "n6", "g1"):
            assert text_of(path, event_id) == "[forgotten]"
        for event_id in ("n1", "n2", "n3"):
            assert text_of(path, event_id) != "[forgotten]"
        assert "capture" in text_of(path, "n5")
        assert (await controls.quarantine_report()).count == 0
        assert not rows(
            path,
            "SELECT rowid FROM conversation_event_fts WHERE conversation_event_fts MATCH ?",
            ('"window"*',),
        )
        segments = b"".join(
            r[0]
            for r in rows(path, "SELECT block FROM conversation_event_fts_data")
            if isinstance(r[0], bytes)
        )
        assert b"window" not in segments
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_owner_approved_restore_returns_messages_unchanged(
    tmp_path, authority_parts
):
    path, access, controls, _, _, writer, reader = await open_lab(
        tmp_path, authority_parts
    )
    try:
        await controls.resolve_quarantine("restore")
        summary = authority_parts.hello.calls[-1].material_summary
        assert "may repeat information from a project you forgot" in summary
        assert text_of(path, "n4") == f"Your interview topic is {FACT}."
        assert (await controls.quarantine_report()).count == 0
        recent = await access.snapshot(
            ProjectSelection("nepal", "tn", 0), project_wide=True
        )
        assert "n4" in {s.event.event_id for s in recent.sources}
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_declined_hello_changes_nothing(tmp_path, authority_parts):
    path, _, controls, _, _, writer, reader = await open_lab(tmp_path, authority_parts)
    try:
        authority_parts.hello.denied = True
        from jarvis.capabilities.authority_bridge import CapabilityAuthorizationError

        with pytest.raises(CapabilityAuthorizationError):
            await controls.resolve_quarantine("delete")
        assert (await controls.quarantine_report()).count == 3
        assert text_of(path, "n4") == f"Your interview topic is {FACT}."
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_approval_binds_the_exact_quarantine_shown(tmp_path, authority_parts):
    path, _, controls, issuer, _, writer, reader = await open_lab(
        tmp_path, authority_parts
    )
    try:
        original = issuer.authorize_quarantine_resolution

        def approve_then_change(material):
            handle = original(material)
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "INSERT INTO conversation_event_quarantine VALUES "
                    "('n2','untracked_after_forgotten_project')"
                )
            return handle

        issuer.authorize_quarantine_resolution = approve_then_change
        with pytest.raises(PermissionError, match="quarantine changed"):
            await controls.resolve_quarantine("delete")
        assert text_of(path, "n4") == f"Your interview topic is {FACT}."
        assert text_of(path, "n2") == "Understood."
    finally:
        await reader.close()
        await writer.close()


def test_fresh_database_has_nothing_to_quarantine(tmp_path):
    with sqlite3.connect(tmp_path / "fresh.db") as connection:
        assert MemoryMigrationRunner().apply(connection) == 7
        assert not connection.execute(
            "SELECT 1 FROM conversation_event_quarantine"
        ).fetchall()
