"""SQLite is a transaction fixture; production shares the SQLCipher workers."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from jarvis.authority.conversation_history import (
    ConversationHistoryAuthority,
    HistoryActionBinding,
)
from jarvis.memory.migration_runner import (
    MemoryMigrationRunner,
    discover_memory_migrations,
)
from jarvis.memory.project_conversation_store import (
    ProjectConversationStore,
    archive_digest,
)
from jarvis.memory.project_conversations import ConversationEvent, ProjectSelection
from jarvis.memory.worker import SerialConnectionWorker


def event(event_id="turn-1", text="My vehicle is a Jimny", role="user", **kw):
    return ConversationEvent(
        event_id,
        "segment-1",
        "request-1",
        role,
        text,
        datetime(2026, 10, 30, tzinfo=UTC),
        **kw,
    )


async def setup_store(tmp_path, parts):
    path = tmp_path / "history.db"
    # Prove upgrading an actual version-4 database rather than only fresh creation.
    with sqlite3.connect(path) as conn:
        MemoryMigrationRunner(discover_memory_migrations()[:4]).apply(conn)
        assert MemoryMigrationRunner().apply(conn) == 5
    writer = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="history-write"
    )
    reader = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="history-read"
    )
    issuer = ConversationHistoryAuthority(parts.broker)
    grant = issuer.open("runtime", "gemini")
    store = ProjectConversationStore(writer=writer, reader=reader, authority=issuer)
    selection = ProjectSelection("project-nepal", "thread-nepal", 0)

    def permit(operation, material, source=None, source_id="bootstrap"):
        issuer.register_source(
            grant, source.event_id if source else source_id, source=source
        )
        return issuer.issue_child(
            grant,
            HistoryActionBinding(
                operation,
                source.event_id if source else source_id,
                archive_digest(material),
                targets=(
                    ("project", selection.project_id),
                    ("thread", selection.thread_id),
                ),
            ),
        )

    material = store.creation_material(selection, "Nepal trip")
    await store.create_project(
        selection, "Nepal trip", permit=permit("admit", material)
    )
    return path, store, selection, permit, writer, reader, issuer, grant


def test_archive_idempotency_preserves_identical_text_and_reopens(
    tmp_path, authority_parts
):
    async def scenario():
        (
            path,
            store,
            selection,
            permit,
            writer,
            reader,
            _issuer,
            _grant,
        ) = await setup_store(tmp_path, authority_parts)
        try:
            first = event()

            async def append(value, revision):
                material = store.append_material(selection, value, revision)
                return await store.append_event(
                    selection,
                    value,
                    permit=permit("admit", material, value),
                    expected_revision=revision,
                )

            one = await append(first, 0)
            duplicate = await append(first, 0)
            two = await append(event("turn-2"), 1)
            assert (one.sequence, duplicate.sequence, two.sequence) == (1, 1, 2)
            assert duplicate.status == "duplicate"
            assert one.revision == 1 and two.revision == 2
        finally:
            await reader.close()
            await writer.close()
        with sqlite3.connect(path) as conn:
            assert conn.execute(
                "SELECT sequence, text FROM conversation_event ORDER BY sequence"
            ).fetchall() == [(1, first.text), (2, first.text)]
            assert conn.execute("PRAGMA user_version").fetchone() == (5,)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change", ["revision", "payload", "project", "source_identity"]
)
def test_wrong_binding_or_stale_revision_rolls_back(tmp_path, authority_parts, change):
    async def scenario():
        (
            path,
            store,
            selection,
            permit,
            writer,
            reader,
            _issuer,
            _grant,
        ) = await setup_store(tmp_path, authority_parts)
        value = event()
        material = store.append_material(selection, value, 0)
        token = permit("admit", material, value)
        attempted, revision, target = value, 0, selection
        if change == "revision":
            revision = 1
        elif change == "payload":
            attempted = replace(value, text="tampered")
        elif change == "source_identity":
            attempted = replace(value)
        else:
            target = replace(selection, project_id="unrelated")
        try:
            with pytest.raises((PermissionError, ValueError)):
                await store.append_event(
                    target, attempted, permit=token, expected_revision=revision
                )
            with sqlite3.connect(path) as conn:
                assert conn.execute(
                    "SELECT count(*) FROM conversation_event"
                ).fetchone() == (0,)
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "role,delivery", [("assistant", "partial"), ("tool", "complete")]
)
def test_archive_keeps_delivery_and_source_role(
    tmp_path, authority_parts, role, delivery
):
    async def scenario():
        (
            path,
            store,
            selection,
            permit,
            writer,
            reader,
            _issuer,
            _grant,
        ) = await setup_store(tmp_path, authority_parts)
        value = event(role=role, delivery=delivery)
        try:
            material = store.append_material(selection, value, 0)
            await store.append_event(
                selection,
                value,
                permit=permit("admit", material, value),
                expected_revision=0,
            )
            with sqlite3.connect(path) as conn:
                assert conn.execute(
                    "SELECT role, delivery, request_id, segment_id FROM conversation_event"
                ).fetchone() == (role, delivery, "request-1", "segment-1")
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_revoked_history_permission_blocks_append(tmp_path, authority_parts):
    async def scenario():
        (
            path,
            store,
            selection,
            permit,
            writer,
            reader,
            issuer,
            grant,
        ) = await setup_store(tmp_path, authority_parts)
        value = event()
        token = permit("admit", store.append_material(selection, value, 0), value)
        issuer.revoke(grant)
        try:
            with pytest.raises(PermissionError):
                await store.append_event(
                    selection, value, permit=token, expected_revision=0
                )
            with sqlite3.connect(path) as conn:
                assert conn.execute(
                    "SELECT count(*) FROM conversation_event"
                ).fetchone() == (0,)
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_archive_conflict_with_correctly_bound_permit_is_rejected(
    tmp_path, authority_parts
):
    async def scenario():
        (
            _path,
            store,
            selection,
            permit,
            writer,
            reader,
            _issuer,
            _grant,
        ) = await setup_store(tmp_path, authority_parts)
        value = event()
        try:
            token = permit("admit", store.append_material(selection, value, 1), value)
            with pytest.raises(PermissionError, match="archive revision changed"):
                await store.append_event(
                    selection, value, permit=token, expected_revision=1
                )
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["storage", "revocation"])
def test_failure_during_transaction_rolls_back_event_and_sequence(
    tmp_path, authority_parts, failure
):
    async def scenario():
        (
            path,
            store,
            selection,
            permit,
            writer,
            reader,
            issuer,
            grant,
        ) = await setup_store(tmp_path, authority_parts)
        value = event()
        try:
            if failure == "storage":
                await writer.run(
                    lambda conn: conn.execute(
                        "CREATE TRIGGER reject_event BEFORE INSERT ON conversation_event "
                        "BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END"
                    )
                )
            else:

                def tracing(conn):
                    def revoke_on_insert(statement):
                        if statement.startswith("INSERT INTO conversation_event"):
                            issuer.revoke(grant, "during_commit")

                    conn.set_trace_callback(revoke_on_insert)

                await writer.run(tracing)
            token = permit("admit", store.append_material(selection, value, 0), value)
            with pytest.raises((PermissionError, sqlite3.IntegrityError)):
                await store.append_event(
                    selection, value, permit=token, expected_revision=0
                )
            with sqlite3.connect(path) as conn:
                assert conn.execute(
                    "SELECT count(*) FROM conversation_event"
                ).fetchone() == (0,)
                assert conn.execute(
                    "SELECT last_sequence,archive_revision FROM conversation_thread"
                ).fetchone() == (0, 0)
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())
