from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from jarvis.memory.migrations import (
    MemoryMigrationIntegrityError,
    MemoryMigrationRunner,
    MemorySchemaTooNewError,
    discover_memory_migrations,
)


def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA secure_delete = ON")
    return conn


def insert_source(conn: sqlite3.Connection, source_id: str = "source-1") -> None:
    conn.execute(
        """
        INSERT INTO memory_source (
            source_id,
            source_class,
            canonical_ref,
            observed_at,
            authority_class,
            sensitivity,
            created_at
        ) VALUES (?, 'owner_explicit', ?, ?, 'owner_explicit', 'standard', ?)
        """,
        (
            source_id,
            "conversation:session-1:turn-1",
            "2026-09-05T05:00:00Z",
            "2026-09-05T05:00:00Z",
        ),
    )


def insert_assertion(
    conn: sqlite3.Connection,
    *,
    assertion_id: str = "assertion-1",
    normalized_text: str = "Jimny mountain setup",
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO semantic_assertion (
            assertion_id,
            subject_scope,
            subject,
            predicate,
            value_type,
            value_json,
            normalized_text,
            source_id,
            valid_from,
            system_from,
            state,
            verification_state,
            freshness_class,
            sensitivity,
            created_at,
            updated_at
        ) VALUES (
            ?, 'owner', 'owner', 'vehicle_preference', 'text', ?, ?, 'source-1',
            '2026-09-05T05:00:00Z', '2026-09-05T05:00:00Z', 'active',
            'verified', 'stable', 'standard',
            '2026-09-05T05:00:00Z', '2026-09-05T05:00:00Z'
        )
        """,
        (assertion_id, '"235/75 R15"', normalized_text),
    )
    return int(cursor.lastrowid)


def test_initial_migration_creates_versioned_canonical_schema() -> None:
    conn = connection()
    runner = MemoryMigrationRunner(
        clock=lambda: datetime(2026, 9, 5, 5, 30, tzinfo=UTC)
    )

    version = runner.apply(conn)

    assert version == 1
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    ledger = conn.execute(
        "SELECT version, name, length(sha256), applied_at FROM jarvis_schema_migration"
    ).fetchone()
    assert ledger == (
        1,
        "0001_initial.sql",
        64,
        "2026-09-05T05:30:00Z",
    )
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }
    assert {
        "memory_source",
        "semantic_assertion",
        "memory_operation",
        "semantic_assertion_fts",
        "current_semantic_assertion",
    } <= tables


def test_migration_is_idempotent_and_checksum_protected() -> None:
    conn = connection()
    migrations = discover_memory_migrations()
    runner = MemoryMigrationRunner(migrations)
    assert runner.apply(conn) == 1
    assert runner.apply(conn) == 1

    tampered = replace(migrations[0], sha256="0" * 64)
    with pytest.raises(MemoryMigrationIntegrityError, match="checksum"):
        MemoryMigrationRunner((tampered,)).apply(conn)


def test_newer_database_and_ledger_drift_fail_closed() -> None:
    conn = connection()
    runner = MemoryMigrationRunner()
    runner.apply(conn)

    conn.execute("PRAGMA user_version = 99")
    with pytest.raises(MemorySchemaTooNewError):
        runner.apply(conn)

    conn.execute("PRAGMA user_version = 1")
    conn.execute("DELETE FROM jarvis_schema_migration")
    with pytest.raises(MemoryMigrationIntegrityError, match="ledger count"):
        runner.apply(conn)


def test_fts_triggers_track_insert_update_delete_and_rebuild() -> None:
    conn = connection()
    MemoryMigrationRunner().apply(conn)
    insert_source(conn)
    rowid = insert_assertion(conn, normalized_text="mountainjimny setup")

    assert conn.execute(
        "SELECT rowid FROM semantic_assertion_fts WHERE semantic_assertion_fts MATCH ?",
        ("mountainjimny",),
    ).fetchall() == [(rowid,)]

    conn.execute(
        "UPDATE semantic_assertion SET normalized_text = ? WHERE assertion_id = ?",
        ("cityjimny setup", "assertion-1"),
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM semantic_assertion_fts WHERE semantic_assertion_fts MATCH ?",
            ("mountainjimny",),
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM semantic_assertion_fts WHERE semantic_assertion_fts MATCH ?",
            ("cityjimny",),
        ).fetchone()[0]
        == 1
    )

    conn.execute(
        "INSERT INTO semantic_assertion_fts(semantic_assertion_fts, rowid, normalized_text) "
        "VALUES('delete', ?, ?)",
        (rowid, "cityjimny setup"),
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM semantic_assertion_fts WHERE semantic_assertion_fts MATCH ?",
            ("cityjimny",),
        ).fetchone()[0]
        == 0
    )

    conn.execute(
        "INSERT INTO semantic_assertion_fts(semantic_assertion_fts) VALUES('rebuild')"
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM semantic_assertion_fts WHERE semantic_assertion_fts MATCH ?",
            ("cityjimny",),
        ).fetchone()[0]
        == 1
    )

    conn.execute(
        "DELETE FROM semantic_assertion WHERE assertion_id = ?", ("assertion-1",)
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM semantic_assertion_fts WHERE semantic_assertion_fts MATCH ?",
            ("cityjimny",),
        ).fetchone()[0]
        == 0
    )


def test_fts_and_core_secure_delete_are_enabled() -> None:
    conn = connection()
    MemoryMigrationRunner().apply(conn)

    assert conn.execute("PRAGMA secure_delete").fetchone()[0] == 1
    config = dict(
        conn.execute("SELECT k, v FROM semantic_assertion_fts_config").fetchall()
    )
    assert int(config["secure-delete"]) == 1


def test_current_view_excludes_closed_lifecycle_states() -> None:
    conn = connection()
    MemoryMigrationRunner().apply(conn)
    insert_source(conn)
    insert_assertion(conn)

    assert (
        conn.execute("SELECT count(*) FROM current_semantic_assertion").fetchone()[0]
        == 1
    )

    conn.execute(
        """
        UPDATE semantic_assertion
        SET state = 'superseded',
            valid_to = '2026-09-06T00:00:00Z',
            system_to = '2026-09-06T00:00:00Z',
            updated_at = '2026-09-06T00:00:00Z'
        WHERE assertion_id = 'assertion-1'
        """
    )
    assert (
        conn.execute("SELECT count(*) FROM current_semantic_assertion").fetchone()[0]
        == 0
    )
