from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from jarvis.incidents import SqliteIncidentStore
from jarvis.incidents.migration_runner import (
    EngineeringMigrationIntegrityError,
    EngineeringMigrationRunner,
    EngineeringSchemaTooNewError,
    discover_engineering_migrations,
)


def test_incident_store_applies_versioned_engineering_schema(tmp_path) -> None:
    path = tmp_path / "incidents.sqlite3"
    store = SqliteIncidentStore(path)
    store.close()

    connection = sqlite3.connect(path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()
        assert version is not None
        assert int(version[0]) == EngineeringMigrationRunner().latest_version

        rows = connection.execute(
            """
            SELECT version, name, sha256
            FROM jarvis_engineering_schema_migration
            ORDER BY version
            """
        ).fetchall()
        migrations = discover_engineering_migrations()
        assert rows == [
            (item.version, item.name, item.sha256)
            for item in migrations
        ]
    finally:
        connection.close()


def test_engineering_migration_history_rejects_checksum_drift() -> None:
    connection = sqlite3.connect(":memory:")
    migrations = discover_engineering_migrations()
    runner = EngineeringMigrationRunner(
        migrations,
        clock=lambda: datetime(2026, 9, 24, tzinfo=UTC),
    )
    runner.apply(connection)

    connection.execute(
        """
        UPDATE jarvis_engineering_schema_migration
        SET sha256 = ?
        WHERE version = 1
        """,
        ("0" * 64,),
    )
    connection.commit()

    with pytest.raises(
        EngineeringMigrationIntegrityError,
        match="checksum differs",
    ):
        runner.apply(connection)
    connection.close()


def test_engineering_schema_newer_than_runtime_fails_closed() -> None:
    connection = sqlite3.connect(":memory:")
    runner = EngineeringMigrationRunner()
    connection.execute(f"PRAGMA user_version = {runner.latest_version + 1}")

    with pytest.raises(EngineeringSchemaTooNewError):
        runner.apply(connection)
    connection.close()


def test_packaged_engineering_migration_catalog_rejects_mutation() -> None:
    migrations = discover_engineering_migrations()
    changed = replace(
        migrations[0],
        sha256="short",
    )

    with pytest.raises(EngineeringMigrationIntegrityError, match="invalid SHA-256"):
        EngineeringMigrationRunner((changed,))
