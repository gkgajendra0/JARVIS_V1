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


def test_phase1h_database_upgrades_to_phase2a_without_repair_data_loss(
    tmp_path,
) -> None:
    path = tmp_path / "incidents.sqlite3"
    connection = sqlite3.connect(path)
    migrations = discover_engineering_migrations()
    assert len(migrations) >= 3
    phase1h_runner = EngineeringMigrationRunner(migrations[:2])
    phase1h_runner.apply(connection)
    connection.execute(
        """
        INSERT INTO engineering_incident (
            incident_id, title, symptom, severity, status,
            created_at_epoch, updated_at_epoch, affected_components_json,
            root_cause, accepted_fix, regression_tests_json, commit_sha,
            pr_number, deployment_result, rollback_status, lessons_json
        ) VALUES (
            'incident-phase1h', 'Phase 1H incident', 'runtime exited',
            'warning', 'open', 10.0, 10.0, '["runtime.voice"]',
            NULL, NULL, '[]', NULL, NULL, NULL, NULL, '[]'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO engineering_repair_attempt (
            attempt_id, incident_id, trigger_id, policy_id, policy_version,
            action_id, action_kind, risk_class, component_id,
            action_created_at_epoch, attempt_number, started_at_epoch,
            pre_repair_evidence_json, trigger_snapshot_json,
            policy_snapshot_json, policy_digest,
            finished_at_epoch, execution_result,
            post_repair_evidence_json, verifier_result, verification_json,
            next_retry_eligible_epoch, verdict
        ) VALUES (
            'attempt-phase1h', 'incident-phase1h', 'trigger-phase1h',
            'runtime-child-exit-v1', 1, 'action-phase1h',
            'restart_runtime_child', 2, 'runtime.voice',
            11.0, 1, 11.0, '[]', NULL, NULL, NULL,
            NULL, NULL, '[]', NULL, NULL, NULL, NULL
        )
        """
    )
    connection.commit()
    connection.close()

    store = SqliteIncidentStore(path)
    try:
        incident = store.get("incident-phase1h")
        attempt = store.get_repair_attempt("attempt-phase1h")
        assert incident is not None
        assert incident.title == "Phase 1H incident"
        assert attempt is not None
        assert attempt.attempt_id == "attempt-phase1h"
        assert attempt.action.component_id == "runtime.voice"
    finally:
        store.close()

    connection = sqlite3.connect(path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()
        assert version is not None
        assert int(version[0]) == EngineeringMigrationRunner().latest_version
        tables = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }
        assert "engineering_knowledge_revision" in tables
        assert "engineering_knowledge_facet" in tables
        assert "engineering_attestation" in tables
    finally:
        connection.close()


def test_phase2a_engineering_knowledge_rows_are_immutable(tmp_path) -> None:
    path = tmp_path / "incidents.sqlite3"
    store = SqliteIncidentStore(path)
    store.close()

    connection = sqlite3.connect(path)
    connection.execute(
        """
        INSERT INTO engineering_knowledge_identity (
            knowledge_id, stable_label, created_at_epoch, created_by
        ) VALUES ('knowledge-1', 'runtime recovery', 1.0, 'test')
        """
    )
    connection.execute(
        """
        INSERT INTO engineering_knowledge_revision (
            revision_id, knowledge_id, revision_number,
            kind_namespace, normalized_summary,
            system_from_epoch, sensitivity, freshness_state,
            canonicalization, digest_algorithm, canonical_digest,
            created_at_epoch, created_by
        ) VALUES (
            'revision-1', 'knowledge-1', 1,
            'jarvis.repair', 'repair summary',
            1.0, 'standard', 'current',
            'rfc8785', 'sha256',
            ?, 1.0, 'test'
        )
        """,
        ("a" * 64,),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            """
            UPDATE engineering_knowledge_revision
            SET normalized_summary = 'mutated'
            WHERE revision_id = 'revision-1'
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            """
            DELETE FROM engineering_knowledge_revision
            WHERE revision_id = 'revision-1'
            """
        )

    connection.close()


def test_phase2a_database_upgrades_to_retrieval_schema_without_canonical_loss(
    tmp_path,
) -> None:
    path = tmp_path / "incidents.sqlite3"
    connection = sqlite3.connect(path)
    migrations = discover_engineering_migrations()
    assert len(migrations) >= 4
    EngineeringMigrationRunner(migrations[:3]).apply(connection)
    connection.execute(
        """
        INSERT INTO engineering_knowledge_identity (
            knowledge_id, stable_label, created_at_epoch, created_by
        ) VALUES ('knowledge-v3', 'preserve me', 1.0, 'test')
        """
    )
    connection.execute(
        """
        INSERT INTO engineering_knowledge_revision (
            revision_id, knowledge_id, revision_number,
            kind_namespace, normalized_summary,
            system_from_epoch, sensitivity, freshness_state,
            canonicalization, digest_algorithm, canonical_digest,
            created_at_epoch, created_by
        ) VALUES (
            'revision-v3', 'knowledge-v3', 1,
            'jarvis.repair', 'canonical knowledge survives retrieval migration',
            1.0, 'standard', 'current',
            'rfc8785', 'sha256',
            ?, 1.0, 'test'
        )
        """,
        ("a" * 64,),
    )
    connection.commit()
    connection.close()

    store = SqliteIncidentStore(path)
    store.close()

    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            """
            SELECT knowledge_id, normalized_summary
            FROM engineering_knowledge_revision
            WHERE revision_id = 'revision-v3'
            """
        ).fetchone() == (
            "knowledge-v3",
            "canonical knowledge survives retrieval migration",
        )
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
        assert "engineering_knowledge_search_document" in tables
        assert "engineering_knowledge_embedding" in tables
        assert "engineering_knowledge_fts" in tables
    finally:
        connection.close()
