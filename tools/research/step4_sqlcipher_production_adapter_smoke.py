from __future__ import annotations

import argparse
import json
import shutil
import sqlite3 as stdlib_sqlite
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from jarvis.memory.database import SqlCipherMemoryDatabaseFactory  # noqa: E402
from jarvis.security import WindowsDpapiKeyProtector  # noqa: E402

MARKER = "JARVIS_PRODUCTION_ADAPTER_MARKER_HINDI_स्मृति"


def scalar(connection: object, sql: str) -> object:
    row = connection.execute(sql).fetchone()  # type: ignore[attr-defined]
    return None if row is None else row[0]


def plaintext_sqlite_blocked(path: Path) -> bool:
    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        connection = stdlib_sqlite.connect(uri, uri=True)
        try:
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            connection.close()
    except stdlib_sqlite.DatabaseError:
        return True
    return False


def marker_leaks(paths: list[Path]) -> list[str]:
    needle = MARKER.encode("utf-8")
    return [path.name for path in paths if path.exists() and needle in path.read_bytes()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact-dir",
        default=".step4-sqlcipher-production-adapter",
    )
    parser.add_argument(
        "--output",
        default=".step4-sqlcipher-production-adapter.json",
    )
    args = parser.parse_args()

    if sys.platform != "win32":
        raise SystemExit("The production SQLCipher adapter smoke must run on Windows.")

    artifact_dir = Path(args.artifact_dir)
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True)

    database_path = artifact_dir / "memory.db"
    factory = SqlCipherMemoryDatabaseFactory(
        database_path,
        key_protector=WindowsDpapiKeyProtector(),
    )

    print("STEP4_PRODUCTION_ADAPTER_STAGE=first_open", flush=True)
    connection = factory.open()
    try:
        first_cipher_status = scalar(connection, "PRAGMA cipher_status")
        first_cipher_version = scalar(connection, "PRAGMA cipher_version")
        first_sqlite_version = scalar(connection, "SELECT sqlite_version()")
        first_user_version = scalar(connection, "PRAGMA user_version")
        connection.execute(
            """
            INSERT INTO memory_source (
                source_id,
                source_class,
                canonical_ref,
                observed_at,
                authority_class,
                sensitivity,
                created_at
            ) VALUES (
                'source-smoke',
                'owner_explicit',
                'conversation:smoke:turn-1',
                '2026-09-05T06:00:00Z',
                'owner_explicit',
                'standard',
                '2026-09-05T06:00:00Z'
            )
            """
        )
        connection.execute(
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
                'assertion-smoke',
                'owner',
                'owner',
                'smoke_preference',
                'text',
                ?,
                ?,
                'source-smoke',
                '2026-09-05T06:00:00Z',
                '2026-09-05T06:00:00Z',
                'active',
                'verified',
                'stable',
                'standard',
                '2026-09-05T06:00:00Z',
                '2026-09-05T06:00:00Z'
            )
            """,
            (json.dumps(MARKER, ensure_ascii=False), MARKER),
        )
        connection.commit()
        first_fts_hits = scalar(
            connection,
            "SELECT count(*) FROM semantic_assertion_fts "
            "WHERE semantic_assertion_fts MATCH 'JARVIS_PRODUCTION_ADAPTER_MARKER_HINDI'",
        )
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()

    print("STEP4_PRODUCTION_ADAPTER_STAGE=reopen", flush=True)
    reopened = factory.open()
    try:
        reopened_count = scalar(
            reopened,
            "SELECT count(*) FROM current_semantic_assertion "
            "WHERE assertion_id = 'assertion-smoke'",
        )
        reopened_fts_hits = scalar(
            reopened,
            "SELECT count(*) FROM semantic_assertion_fts "
            "WHERE semantic_assertion_fts MATCH 'JARVIS_PRODUCTION_ADAPTER_MARKER_HINDI'",
        )
        migration_count = scalar(
            reopened,
            "SELECT count(*) FROM jarvis_schema_migration",
        )
        reopened.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        reopened.close()

    leak_paths = [
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
        factory.key_path,
    ]
    leaks = marker_leaks(leak_paths)

    checks = {
        "cipher_status": first_cipher_status == 1,
        "cipher_version": str(first_cipher_version).startswith("4.17.0"),
        "sqlite_version": first_sqlite_version == "3.53.3",
        "migration_version": first_user_version == 1,
        "migration_ledger_single": migration_count == 1,
        "fts_first_open": first_fts_hits == 1,
        "reopen_current_assertion": reopened_count == 1,
        "reopen_fts": reopened_fts_hits == 1,
        "protected_key_exists": factory.key_path.exists(),
        "stdlib_plaintext_open_blocked": plaintext_sqlite_blocked(database_path),
        "marker_not_visible_in_storage_artifacts": not leaks,
    }
    result = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "sqlcipher_version": first_cipher_version,
        "sqlite_version": first_sqlite_version,
        "leaks": leaks,
        "database_path": str(database_path),
        "key_path": str(factory.key_path),
        "note": "Synthetic production-adapter smoke; no raw SQLCipher key is reported.",
    }
    Path(args.output).write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=True))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
