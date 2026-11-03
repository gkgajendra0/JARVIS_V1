"""Rehearse the memory schema migration on a COPY of the production database.

Before the merged build ever opens the real ``memory.db``, this copies the
stopped database (``memory.db`` plus any ``-wal``/``-shm``) and its sealed key
into a new, empty work folder, opens the copy through the normal SQLCipher +
DPAPI path, and applies the migrations there. It reports, with counts only
(never content):

- the schema version before and after (production today: 3; after: 7);
- ``PRAGMA integrity_check`` and ``foreign_key_check`` after migrating;
- the row count of every table that existed before, which must be unchanged;
- the tables the migration added.

The source files are hashed before and after and must be byte-identical: the
rehearsal never writes to them. Run it as the owner (DPAPI), with Jarvis
stopped. Delete the work folder afterwards; it holds an encrypted copy.

``python -m jarvis.memory.migration_rehearsal --source <LocalState\\memory.db>
--work <new empty folder>``
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

_SIDE_FILES = ("-wal", "-shm")


class RehearsalError(RuntimeError):
    pass


class _NoMigration:
    """Opens the copy at its current version (no migration), to count rows."""

    def apply(self, connection: Any) -> int:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _digest(paths) -> dict[str, str]:
    result = {}
    for path in paths:
        if path.exists():
            result[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _source_files(database: Path, key: Path) -> list[Path]:
    files = [database, key]
    files += [database.with_name(database.name + s) for s in _SIDE_FILES]
    return files


def _tables(connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _counts(connection, tables) -> dict[str, int]:
    counts = {}
    for name in tables:
        quoted = '"' + name.replace('"', '""') + '"'
        try:
            counts[name] = int(
                connection.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]
            )
        except Exception:  # noqa: BLE001 - e.g. FTS shadow tables; reported as -1
            counts[name] = -1
    return counts


def rehearse(
    database: Path,
    key: Path,
    work: Path,
    open_copy: Callable[[Path, Path, Any], Any],
    latest_version: int,
) -> dict:
    """Copy, migrate the copy, verify. ``open_copy(db, key, runner)`` opens a
    connection the way production does (SQLCipher + DPAPI in real use)."""
    database, key, work = Path(database), Path(key), Path(work)
    if not database.is_file() or not key.is_file():
        raise RehearsalError("source database or its sealed key is missing")
    if work.exists() and any(work.iterdir()):
        raise RehearsalError("work folder must be new or empty")
    if work.resolve() == database.parent.resolve():
        raise RehearsalError("work folder must not be the production data folder")
    sources = _source_files(database, key)
    before_hashes = _digest(sources)
    work.mkdir(parents=True, exist_ok=True)
    for path in sources:
        if path.exists():
            shutil.copy2(path, work / path.name)
    copy_db, copy_key = work / database.name, work / key.name

    connection = open_copy(copy_db, copy_key, _NoMigration())
    try:
        version_before = int(connection.execute("PRAGMA user_version").fetchone()[0])
        tables_before = _tables(connection)
        counts_before = _counts(connection, tables_before)
    finally:
        connection.close()

    from jarvis.memory.migration_runner import MemoryMigrationRunner

    connection = open_copy(copy_db, copy_key, MemoryMigrationRunner())
    try:
        version_after = int(connection.execute("PRAGMA user_version").fetchone()[0])
        integrity = [r[0] for r in connection.execute("PRAGMA integrity_check")]
        foreign = connection.execute("PRAGMA foreign_key_check").fetchall()
        tables_after = _tables(connection)
        counts_after = _counts(connection, tables_before)
    finally:
        connection.close()

    after_hashes = _digest(sources)
    # The migration ledger gains one row per applied migration, by design.
    changed = sorted(
        name
        for name in tables_before
        if name != "jarvis_schema_migration"
        and counts_before[name] != counts_after[name]
    )
    checks = {
        "source_unchanged": before_hashes == after_hashes,
        "migrated_to_latest": version_after == latest_version,
        "integrity_ok": integrity == ["ok"],
        "foreign_keys_ok": not foreign,
        "existing_rows_unchanged": not changed,
    }
    return {
        "verdict": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "version_before": version_before,
        "version_after": version_after,
        "latest_version": latest_version,
        "tables_added": sorted(set(tables_after) - set(tables_before)),
        "row_counts_before": counts_before,
        "tables_with_changed_counts": changed,
        "integrity": integrity[:5],
        "foreign_key_violations": len(foreign),
    }


def main(argv=None) -> int:
    import argparse
    import os

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("needs Windows DPAPI and the SQLCipher runtime")
    from jarvis.memory.database import (
        SqlCipherMemoryDatabaseFactory,
        default_memory_key_path,
    )
    from jarvis.memory.migration_runner import MemoryMigrationRunner
    from jarvis.security.dpapi import WindowsDpapiKeyProtector

    source = args.source.resolve(strict=True)
    key = default_memory_key_path(source)

    def open_copy(db, key_path, runner):
        return SqlCipherMemoryDatabaseFactory(
            db,
            key_protector=WindowsDpapiKeyProtector(),
            key_path=key_path,
            migration_runner=runner,
        ).open()

    report = rehearse(
        source,
        key,
        args.work.resolve(),
        open_copy,
        MemoryMigrationRunner().latest_version,
    )
    out = args.work.resolve() / "migration-rehearsal.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Migration rehearsal: {report['verdict']}  ({out})")
    for name, ok in report["checks"].items():
        print(f"  {'ok ' if ok else 'FAIL'} {name}")
    print(
        f"  schema {report['version_before']} -> {report['version_after']}; "
        f"added: {', '.join(report['tables_added']) or 'none'}"
    )
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
