"""Inspection must never initialise/migrate memory or allow writes."""

import pytest
from test_memory_database import StubKeyProtector

from jarvis.memory import database as m


def open_read_only(path):
    return m.open_existing_memory_database_read_only(
        path, key_protector=StubKeyProtector()
    )


def test_missing_database_creates_neither_directory_nor_key(tmp_path):
    path = tmp_path / "missing" / "memory.db"
    with pytest.raises(m.MemoryDatabaseError):
        open_read_only(path)
    assert not path.parent.exists()


def encrypted_fixture(tmp_path):
    driver = pytest.importorskip("sqlcipher3")
    path = tmp_path / "encrypted memory #1.db"
    factory = m.SqlCipherMemoryDatabaseFactory(path, key_protector=StubKeyProtector())
    c = factory.open()
    c.execute("CREATE TABLE inspection_probe(value TEXT)")
    c.execute("INSERT INTO inspection_probe VALUES ('preserve me')")
    c.commit()
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    return path, factory.key_path, driver


def test_encrypted_inspection_denies_writes_and_preserves_bytes_and_schema(tmp_path):
    path, key, driver = encrypted_fixture(tmp_path)
    before = path.read_bytes(), key.read_bytes()
    c = open_read_only(path)
    try:
        assert c.execute("SELECT value FROM inspection_probe").fetchone() == (
            "preserve me",
        )
        assert c.execute("PRAGMA user_version").fetchone()[0] == 7
        with pytest.raises(driver.OperationalError):
            c.execute("DELETE FROM inspection_probe")
        c.execute("PRAGMA query_only = OFF")
        with pytest.raises(driver.OperationalError):
            c.execute("CREATE TABLE must_not_exist(x)")
    finally:
        c.close()
    assert (path.read_bytes(), key.read_bytes()) == before


def test_read_only_inspection_does_not_run_migrations(tmp_path):
    path, _key, _ = encrypted_fixture(tmp_path)
    # A deliberately older marker must be reported unchanged, never repaired.
    factory = m.SqlCipherMemoryDatabaseFactory(path, key_protector=StubKeyProtector())
    c = factory.open()
    c.execute("PRAGMA user_version=6")
    c.commit()
    c.close()
    c = open_read_only(path)
    try:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 6
    finally:
        c.close()


def test_missing_protected_key_is_not_replaced(tmp_path):
    path, key, _ = encrypted_fixture(tmp_path)
    key.unlink()
    before = path.read_bytes()
    with pytest.raises(m.MemoryDatabaseKeyError):
        open_read_only(path)
    assert not key.exists()
    assert path.read_bytes() == before


def test_wrong_key_cannot_read_or_modify_encrypted_database(tmp_path):
    path, key, _ = encrypted_fixture(tmp_path)
    key.write_bytes(
        StubKeyProtector().seal(b"X" * 32, purpose="memory-sqlcipher-master-key-v1")
    )
    before = path.read_bytes()
    with pytest.raises(m.MemoryDatabaseEncryptionError):
        open_read_only(path)
    assert path.read_bytes() == before


def test_read_only_connection_sees_committed_live_wal_rows(tmp_path):
    path, _, _ = encrypted_fixture(tmp_path)
    writer = m.SqlCipherMemoryDatabaseFactory(
        path, key_protector=StubKeyProtector()
    ).open()
    try:
        writer.execute("INSERT INTO inspection_probe VALUES ('committed in WAL')")
        writer.commit()
        reader = open_read_only(path)
        try:
            assert (
                reader.execute("SELECT count(*) FROM inspection_probe").fetchone()[0]
                == 2
            )
        finally:
            reader.close()
    finally:
        writer.close()


def _sidecars(path):
    return sorted(p.name for p in path.parent.iterdir() if p.name != path.name)


def _wal_database(tmp_path):
    import sqlite3

    path = tmp_path / "plain.db"
    c = sqlite3.connect(path)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE t(x)")
    c.execute("INSERT INTO t VALUES (1)")
    c.commit()
    c.close()
    return path


def test_plain_read_only_leaves_wal_files_behind(tmp_path):
    # The defect: URI mode=ro alone creates -wal/-shm beside a cleanly closed
    # WAL database (the production state when Jarvis is stopped) and, being
    # read-only, cannot remove them.
    import sqlite3

    path = _wal_database(tmp_path)
    c = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    c.execute("SELECT count(*) FROM t").fetchone()
    c.close()
    assert _sidecars(path) == ["plain.db-shm", "plain.db-wal"]


def test_inspection_uri_creates_no_files_for_a_closed_database(tmp_path):
    import sqlite3

    path = _wal_database(tmp_path)
    before = path.read_bytes()
    c = sqlite3.connect(m.read_only_uri(path), uri=True)
    try:
        assert c.execute("SELECT count(*) FROM t").fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError):
            c.execute("INSERT INTO t VALUES (2)")
    finally:
        c.close()
    assert _sidecars(path) == []
    assert path.read_bytes() == before


def test_inspection_uri_reads_committed_wal_rows_of_a_live_database(tmp_path):
    import sqlite3

    path = _wal_database(tmp_path)
    writer = sqlite3.connect(path)
    try:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO t VALUES (2)")
        writer.commit()
        assert "immutable" not in m.read_only_uri(path)
        reader = sqlite3.connect(m.read_only_uri(path), uri=True)
        try:
            assert reader.execute("SELECT count(*) FROM t").fetchone() == (2,)
        finally:
            reader.close()
    finally:
        writer.close()


def test_encrypted_inspection_of_a_closed_database_creates_no_files(tmp_path):
    path, key, _ = encrypted_fixture(tmp_path)
    assert not path.with_name(path.name + "-wal").exists()
    c = open_read_only(path)
    try:
        assert c.execute("SELECT count(*) FROM inspection_probe").fetchone() == (1,)
    finally:
        c.close()
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([path.name, key.name])
