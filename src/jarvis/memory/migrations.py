from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from typing import Any

_MIGRATION_NAME = re.compile(r"^(?P<version>\d{4})_(?P<label>[a-z0-9_]+)\.sql$")


class MemoryMigrationError(RuntimeError):
    pass


class MemoryMigrationIntegrityError(MemoryMigrationError):
    pass


class MemorySchemaTooNewError(MemoryMigrationError):
    pass


@dataclass(frozen=True, slots=True)
class MemoryMigration:
    version: int
    name: str
    sql: str
    sha256: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("migration clock must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def discover_memory_migrations() -> tuple[MemoryMigration, ...]:
    package_root = resources.files("jarvis.memory.migrations")
    discovered: list[MemoryMigration] = []
    for entry in package_root.iterdir():
        match = _MIGRATION_NAME.fullmatch(entry.name)
        if match is None:
            continue
        raw = entry.read_bytes()
        discovered.append(
            MemoryMigration(
                version=int(match.group("version")),
                name=entry.name,
                sql=raw.decode("utf-8"),
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
    migrations = tuple(sorted(discovered, key=lambda item: item.version))
    _validate_catalog(migrations)
    return migrations


def _validate_catalog(migrations: Sequence[MemoryMigration]) -> None:
    if not migrations:
        raise MemoryMigrationIntegrityError("no memory migrations were packaged")
    expected = list(range(1, len(migrations) + 1))
    actual = [migration.version for migration in migrations]
    if actual != expected:
        raise MemoryMigrationIntegrityError(
            f"memory migration versions must be contiguous from 1: {actual}"
        )
    names = [migration.name for migration in migrations]
    if len(set(names)) != len(names):
        raise MemoryMigrationIntegrityError("memory migration names must be unique")
    for migration in migrations:
        if len(migration.sha256) != 64:
            raise MemoryMigrationIntegrityError(
                f"migration {migration.name} has an invalid SHA-256 digest"
            )


class MemoryMigrationRunner:
    def __init__(
        self,
        migrations: Sequence[MemoryMigration] | None = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        resolved = tuple(migrations) if migrations is not None else discover_memory_migrations()
        _validate_catalog(resolved)
        self._migrations = resolved
        self._clock = clock

    @property
    def latest_version(self) -> int:
        return self._migrations[-1].version

    def apply(self, connection: Any) -> int:
        current = self._user_version(connection)
        if current > self.latest_version:
            raise MemorySchemaTooNewError(
                f"memory schema version {current} is newer than supported "
                f"version {self.latest_version}"
            )

        self._validate_applied_history(connection, current)
        for migration in self._migrations[current:]:
            self._apply_one(connection, migration)
            current = migration.version
            self._validate_applied_history(connection, current)
        return current

    @staticmethod
    def _user_version(connection: Any) -> int:
        row = connection.execute("PRAGMA user_version").fetchone()
        if row is None:
            raise MemoryMigrationIntegrityError("PRAGMA user_version returned no row")
        return int(row[0])

    @staticmethod
    def _ledger_exists(connection: Any) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'jarvis_schema_migration'
            """
        ).fetchone()
        return row is not None

    def _validate_applied_history(self, connection: Any, current: int) -> None:
        ledger_exists = self._ledger_exists(connection)
        if current == 0:
            if ledger_exists:
                raise MemoryMigrationIntegrityError(
                    "migration ledger exists while PRAGMA user_version is 0"
                )
            return
        if not ledger_exists:
            raise MemoryMigrationIntegrityError(
                "PRAGMA user_version is nonzero but migration ledger is missing"
            )

        rows = connection.execute(
            """
            SELECT version, name, sha256
            FROM jarvis_schema_migration
            ORDER BY version
            """
        ).fetchall()
        if len(rows) != current:
            raise MemoryMigrationIntegrityError(
                "migration ledger count does not match PRAGMA user_version"
            )

        for expected, row in zip(self._migrations[:current], rows, strict=True):
            version, name, sha256 = int(row[0]), str(row[1]), str(row[2])
            if version != expected.version:
                raise MemoryMigrationIntegrityError(
                    f"migration ledger version mismatch at {expected.version}"
                )
            if name != expected.name:
                raise MemoryMigrationIntegrityError(
                    f"migration {version} name differs from packaged migration"
                )
            if sha256 != expected.sha256:
                raise MemoryMigrationIntegrityError(
                    f"migration {version} checksum differs from packaged migration"
                )

    def _apply_one(self, connection: Any, migration: MemoryMigration) -> None:
        applied_at = _timestamp_text(self._clock())
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{migration.sql.rstrip()}\n"
            "INSERT INTO jarvis_schema_migration(version, name, sha256, applied_at) "
            f"VALUES ({migration.version}, {_sql_literal(migration.name)}, "
            f"{_sql_literal(migration.sha256)}, {_sql_literal(applied_at)});\n"
            f"PRAGMA user_version = {migration.version};\n"
            "COMMIT;\n"
        )
        try:
            connection.executescript(script)
        except Exception as exc:  # noqa: BLE001 - sqlite/sqlcipher DB-API exception types differ
            try:
                connection.rollback()
            except Exception as rollback_exc:  # noqa: BLE001 - preserve fail-closed state
                raise MemoryMigrationError(
                    f"migration {migration.name} failed and rollback also failed"
                ) from rollback_exc
            raise MemoryMigrationError(f"migration {migration.name} failed") from exc
