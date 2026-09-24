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
        assert rows == [(item.version, item.name, item.sha256) for item in migrations]
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


def test_legacy_incident_database_is_adopted_without_data_loss(tmp_path) -> None:
    path = tmp_path / "incidents.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE engineering_incident (
            incident_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            symptom TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at_epoch REAL NOT NULL,
            updated_at_epoch REAL NOT NULL,
            affected_components_json TEXT NOT NULL,
            root_cause TEXT,
            accepted_fix TEXT,
            regression_tests_json TEXT NOT NULL,
            commit_sha TEXT,
            pr_number INTEGER,
            deployment_result TEXT,
            rollback_status TEXT,
            lessons_json TEXT NOT NULL
        );
        INSERT INTO engineering_incident VALUES (
            'legacy-1', 'Legacy incident', 'legacy symptom', 'warning', 'open',
            1.0, 1.0, '["voice_runtime"]', NULL, NULL, '[]', NULL, NULL,
            NULL, NULL, '[]'
        );
        """
    )
    connection.commit()
    connection.close()

    store = SqliteIncidentStore(path)
    try:
        incident = store.get("legacy-1")
        assert incident is not None
        assert incident.title == "Legacy incident"
    finally:
        store.close()

    connection = sqlite3.connect(path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()
        assert version is not None
        assert int(version[0]) == EngineeringMigrationRunner().latest_version
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(engineering_repair_attempt)"
            ).fetchall()
        }
        assert {
            "trigger_snapshot_json",
            "policy_snapshot_json",
            "policy_digest",
            "verification_json",
        }.issubset(columns)
    finally:
        connection.close()
