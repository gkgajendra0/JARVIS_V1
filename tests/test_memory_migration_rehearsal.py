"""The production migration rehearsal works on a copy and never on the source."""

import hashlib
import sqlite3

import pytest

from jarvis.memory.migration_rehearsal import RehearsalError, rehearse
from jarvis.memory.migration_runner import (
    MemoryMigrationRunner,
    discover_memory_migrations,
)


def production_like(tmp_path):
    """Schema 3 (what the installed build has) with owner data in it."""
    data = tmp_path / "LocalState"
    data.mkdir()
    db = data / "memory.db"
    with sqlite3.connect(db) as c:
        MemoryMigrationRunner(discover_memory_migrations()[:3]).apply(c)
        c.execute("CREATE TABLE owner_notes (id INTEGER PRIMARY KEY, body TEXT)")
        c.executemany(
            "INSERT INTO owner_notes(body) VALUES (?)", [(f"n{i}",) for i in range(25)]
        )
    key = data / "memory.key.dpapi"
    key.write_bytes(b"sealed-key-stand-in")
    return db, key


def open_plain(db, key, runner):  # stands in for SQLCipher + DPAPI
    assert key.is_file()
    connection = sqlite3.connect(db)
    runner.apply(connection)
    return connection


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_rehearsal_migrates_only_the_copy_and_keeps_every_row(tmp_path):
    db, key = production_like(tmp_path)
    before = sha(db), sha(key)
    report = rehearse(db, key, tmp_path / "rehearsal", open_plain, 7)
    assert report["verdict"] == "PASS", report
    assert (report["version_before"], report["version_after"]) == (3, 7)
    assert report["row_counts_before"]["owner_notes"] == 25
    assert report["tables_with_changed_counts"] == []
    assert "conversation_event" in report["tables_added"]
    assert (sha(db), sha(key)) == before  # the source was never written
    with sqlite3.connect(db) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 3
    assert "n1" not in str(report)  # counts only, never content


def test_rehearsal_refuses_unsafe_work_folders(tmp_path):
    db, key = production_like(tmp_path)
    with pytest.raises(RehearsalError):
        rehearse(db, key, db.parent, open_plain, 7)  # the data folder itself
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "x").write_text("x")
    with pytest.raises(RehearsalError):
        rehearse(db, key, busy, open_plain, 7)


def test_lost_rows_fail_the_rehearsal(tmp_path):
    db, key = production_like(tmp_path)

    def lossy(db_path, key_path, runner):
        connection = open_plain(db_path, key_path, runner)
        if isinstance(runner, MemoryMigrationRunner):
            connection.execute("DELETE FROM owner_notes WHERE id < 3")
        return connection

    report = rehearse(db, key, tmp_path / "r", lossy, 7)
    assert report["verdict"] == "FAIL"
    assert report["tables_with_changed_counts"] == ["owner_notes"]
