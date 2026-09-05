from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from jarvis.memory.database import (
    MemoryDatabaseEncryptionError,
    MemoryDatabaseKeyError,
    SqlCipherMemoryDatabaseFactory,
    default_memory_key_path,
)


class StubKeyProtector:
    protector_id = "stub-key-protector"

    def seal(self, plaintext: bytes, *, purpose: str) -> bytes:
        return b"sealed:" + purpose.encode("utf-8") + b":" + plaintext[::-1]

    def unseal(self, sealed: bytes, *, purpose: str) -> bytes:
        prefix = b"sealed:" + purpose.encode("utf-8") + b":"
        if not sealed.startswith(prefix):
            raise RuntimeError("wrong purpose")
        return sealed[len(prefix) :][::-1]


class FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class FakeSqlCipherConnection:
    def __init__(
        self,
        path: str,
        *,
        cipher_status: int = 1,
        cipher_version: str = "4.17.0 community",
        sqlite_version: str = "3.53.3",
    ) -> None:
        self._inner = sqlite3.connect(path)
        self._cipher_status = cipher_status
        self._cipher_version = cipher_version
        self._sqlite_version = sqlite_version
        self._keyed = False
        self.events: list[str] = []

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any:
        normalized = " ".join(sql.split())
        self.events.append(normalized)
        if normalized.startswith("PRAGMA key ="):
            self._keyed = True
            return FakeCursor([])
        if not self._keyed:
            raise RuntimeError("database touched before SQLCipher key")
        if normalized == "PRAGMA cipher_status":
            return FakeCursor([(self._cipher_status,)])
        if normalized == "PRAGMA cipher_version":
            return FakeCursor([(self._cipher_version,)])
        if normalized == "SELECT sqlite_version()":
            return FakeCursor([(self._sqlite_version,)])
        if normalized == "PRAGMA cipher_memory_security = ON":
            return FakeCursor([])
        return self._inner.execute(sql, parameters)

    def executescript(self, script: str) -> Any:
        if not self._keyed:
            raise RuntimeError("database touched before SQLCipher key")
        return self._inner.executescript(script)

    def rollback(self) -> None:
        self._inner.rollback()

    def close(self) -> None:
        self._inner.close()


class FakeSqlCipherDriver:
    def __init__(
        self,
        *,
        cipher_status: int = 1,
        cipher_version: str = "4.17.0 community",
        sqlite_version: str = "3.53.3",
    ) -> None:
        self._cipher_status = cipher_status
        self._cipher_version = cipher_version
        self._sqlite_version = sqlite_version
        self.connections: list[FakeSqlCipherConnection] = []

    def connect(self, path: str) -> FakeSqlCipherConnection:
        connection = FakeSqlCipherConnection(
            path,
            cipher_status=self._cipher_status,
            cipher_version=self._cipher_version,
            sqlite_version=self._sqlite_version,
        )
        self.connections.append(connection)
        return connection


def factory(
    database_path: Path,
    driver: FakeSqlCipherDriver,
) -> SqlCipherMemoryDatabaseFactory:
    return SqlCipherMemoryDatabaseFactory(
        database_path,
        key_protector=StubKeyProtector(),
        driver_loader=lambda: driver,
        random_bytes=lambda size: b"K" * size,
    )


def test_new_database_is_keyed_before_read_and_migrated(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.db"
    driver = FakeSqlCipherDriver()
    database = factory(database_path, driver)

    connection = database.open()
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM jarvis_schema_migration"
        ).fetchone()[0] == 1
    finally:
        connection.close()

    assert database_path.exists()
    assert database.key_path == default_memory_key_path(database_path)
    sealed = database.key_path.read_bytes()
    assert sealed
    assert b"K" * 32 not in sealed
    assert driver.connections[0].events[0].startswith("PRAGMA key =")
    assert driver.connections[0].events[1] == "SELECT count(*) FROM sqlite_master"


def test_existing_database_reuses_protected_key_and_migrations(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.db"
    driver = FakeSqlCipherDriver()
    database = factory(database_path, driver)

    first = database.open()
    first.close()
    sealed_before = database.key_path.read_bytes()

    second = database.open()
    try:
        assert second.execute(
            "SELECT count(*) FROM jarvis_schema_migration"
        ).fetchone()[0] == 1
    finally:
        second.close()

    assert database.key_path.read_bytes() == sealed_before
    assert len(driver.connections) == 2


def test_database_and_key_must_exist_as_a_pair(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.db"
    database_path.write_bytes(b"existing-database")
    driver = FakeSqlCipherDriver()

    with pytest.raises(MemoryDatabaseKeyError, match="key is missing"):
        factory(database_path, driver).open()
    assert driver.connections == []

    database_path.unlink()
    key_path = default_memory_key_path(database_path)
    key_path.write_bytes(b"orphan-key")
    with pytest.raises(MemoryDatabaseKeyError, match="database is missing"):
        factory(database_path, driver).open()
    assert driver.connections == []


@pytest.mark.parametrize(
    ("status", "cipher_version", "sqlite_version"),
    [
        (0, "4.17.0 community", "3.53.3"),
        (1, "4.16.2 community", "3.53.3"),
        (1, "4.17.0 community", "3.52.0"),
    ],
)
def test_unapproved_or_plaintext_runtime_fails_closed_and_cleans_new_files(
    tmp_path: Path,
    status: int,
    cipher_version: str,
    sqlite_version: str,
) -> None:
    database_path = tmp_path / "memory.db"
    driver = FakeSqlCipherDriver(
        cipher_status=status,
        cipher_version=cipher_version,
        sqlite_version=sqlite_version,
    )
    database = factory(database_path, driver)

    with pytest.raises(MemoryDatabaseEncryptionError):
        database.open()

    assert not database_path.exists()
    assert not database.key_path.exists()
    assert not Path(f"{database_path}-wal").exists()
    assert not Path(f"{database_path}-shm").exists()
