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
