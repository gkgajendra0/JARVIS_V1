"""Checksummed SQLite migrations for canonical capability-registry truth."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from typing import Any

_MIGRATION_NAME = re.compile(r"^(?P<version>\d{4})_(?P<label>[a-z0-9_]+)\.sql$")


class CapabilityRegistryMigrationError(RuntimeError):
    pass


class CapabilityRegistryMigrationIntegrityError(CapabilityRegistryMigrationError):
    pass


class CapabilityRegistrySchemaTooNewError(CapabilityRegistryMigrationError):
    pass


@dataclass(frozen=True, slots=True)
class CapabilityRegistryMigration:
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


def discover_capability_registry_migrations() -> tuple[CapabilityRegistryMigration, ...]:
    package_root = resources.files("jarvis.capability_registry.migrations")
    discovered: list[CapabilityRegistryMigration] = []
    for entry in package_root.iterdir():
        match = _MIGRATION_NAME.fullmatch(entry.name)
        if match is None:
            continue
        raw = entry.read_bytes()
        discovered.append(
            CapabilityRegistryMigration(
                version=int(match.group("version")),
                name=entry.name,
                sql=raw.decode("utf-8"),
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
    migrations = tuple(sorted(discovered, key=lambda item: item.version))
    _validate_catalog(migrations)
    return migrations


def _validate_catalog(
    migrations: Sequence[CapabilityRegistryMigration],
) -> None:
    if not migrations:
        raise CapabilityRegistryMigrationIntegrityError(
            "no capability-registry migrations were packaged"
        )
    expected = list(range(1, len(migrations) + 1))
    actual = [migration.version for migration in migrations]
    if actual != expected:
        raise CapabilityRegistryMigrationIntegrityError(
            "capability-registry migration versions must be contiguous from 1: "
            f"{actual}"
        )
    names = [migration.name for migration in migrations]
    if len(names) != len(set(names)):
        raise CapabilityRegistryMigrationIntegrityError(
            "capability-registry migration names must be unique"
        )
    for migration in migrations:
        if len(migration.sha256) != 64:
            raise CapabilityRegistryMigrationIntegrityError(
                f"migration {migration.name} has an invalid SHA-256 digest"
            )


class CapabilityRegistryMigrationRunner:
    def __init__(
        self,
        migrations: Sequence[CapabilityRegistryMigration] | None = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        resolved = (
            tuple(migrations)
            if migrations is not None
            else discover_capability_registry_migrations()
        )
        _validate_catalog(resolved)
        self._migrations = resolved
        self._clock = clock

    @property
    def latest_version(self) -> int:
        return self._migrations[-1].version

    def apply(self, connection: Any) -> int:
        current = self._user_version(connection)
        if current > self.latest_version:
            raise CapabilityRegistrySchemaTooNewError(
                f"capability-registry schema version {current} is newer than "
                f"supported version {self.latest_version}"
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
            raise CapabilityRegistryMigrationIntegrityError(
                "PRAGMA user_version returned no row"
            )
        return int(row[0])

    @staticmethod
    def _ledger_exists(connection: Any) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'jarvis_capability_schema_migration'
            """
        ).fetchone()
        return row is not None

    def _validate_applied_history(self, connection: Any, current: int) -> None:
        ledger_exists = self._ledger_exists(connection)
        if current == 0:
            if ledger_exists:
                raise CapabilityRegistryMigrationIntegrityError(
                    "capability migration ledger exists while user_version is 0"
                )
            return
        if not ledger_exists:
            raise CapabilityRegistryMigrationIntegrityError(
                "capability user_version is nonzero but migration ledger is missing"
            )

        rows = connection.execute(
            """
            SELECT version, name, sha256
            FROM jarvis_capability_schema_migration
            ORDER BY version
            """
        ).fetchall()
        if len(rows) != current:
            raise CapabilityRegistryMigrationIntegrityError(
                "capability migration ledger count does not match user_version"
            )

        for expected, row in zip(self._migrations[:current], rows, strict=True):
            version, name, sha256 = int(row[0]), str(row[1]), str(row[2])
            if version != expected.version:
                raise CapabilityRegistryMigrationIntegrityError(
                    "capability migration ledger version mismatch at "
                    f"{expected.version}"
                )
            if name != expected.name:
                raise CapabilityRegistryMigrationIntegrityError(
                    f"capability migration {version} name differs from packaged "
                    "migration"
                )
            if sha256 != expected.sha256:
                raise CapabilityRegistryMigrationIntegrityError(
                    f"capability migration {version} checksum differs from packaged "
                    "migration"
                )

    def _apply_one(
        self,
        connection: Any,
        migration: CapabilityRegistryMigration,
    ) -> None:
        applied_at = _timestamp_text(self._clock())
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{migration.sql.rstrip()}\n"
            "INSERT INTO jarvis_capability_schema_migration"
            "(version, name, sha256, applied_at) "
            f"VALUES ({migration.version}, {_sql_literal(migration.name)}, "
            f"{_sql_literal(migration.sha256)}, {_sql_literal(applied_at)});\n"
            f"PRAGMA user_version = {migration.version};\n"
            "COMMIT;\n"
        )
        try:
            connection.executescript(script)
        except Exception as exc:
            try:
                connection.rollback()
            except Exception as rollback_exc:
                raise CapabilityRegistryMigrationError(
                    f"capability migration {migration.name} failed and rollback "
                    "also failed"
                ) from rollback_exc
            raise CapabilityRegistryMigrationError(
                f"capability migration {migration.name} failed"
            ) from exc
