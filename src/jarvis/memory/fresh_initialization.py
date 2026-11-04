"""Clean initialization of the canonical memory database (fresh deployment).

The owner chose a fresh memory deployment: existing memory records and
experimental conversations are not preserved. This tool touches exactly the
four memory files in the data folder and nothing else:

    memory.db, memory.db-wal, memory.db-shm, memory.key.dpapi

``initialize``
1. refuses while any Jarvis process runs (a live database must not be moved);
2. MOVES those files into a new folder under ``--retire-to`` (outside the data
   folder, so nothing loads them). Nothing is deleted; the owner may delete
   that folder at any time. Keeping it makes code rollback possible;
3. creates the new database through the production path (SQLCipher 4.17,
   a new random key sealed with Windows DPAPI for this user, migrations to the
   latest schema), then verifies it (see ``verify``).

``verify`` (also run by ``initialize``) opens the database the way Jarvis does
and reports counts only, never content: schema version equals the latest,
SQLCipher active, ``integrity_check`` ok, foreign keys ok, every migration in
the ledger, and with ``--expect-empty`` every data table empty.

``restore --from <retired folder>`` moves the current memory files aside (into
another new retired folder) and moves the chosen set back, for a code rollback
to a build that needs the old schema.

Configuration, credentials, Windows Hello, authority, identity, work and every
other file in the data folder are never read or written.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MEMORY_FILES = ("memory.db", "memory.db-wal", "memory.db-shm", "memory.key.dpapi")
_LEDGER = "jarvis_schema_migration"


class InitializationError(RuntimeError):
    pass


def jarvis_processes(
    process_iter: Callable[[], Iterable[Any]] | None = None,
) -> list[int]:
    """PIDs of running Jarvis processes (voice runtime, supervisor, app)."""
    if process_iter is None:
        import psutil

        def process_iter():
            return psutil.process_iter(["pid", "name", "cmdline"])

    found = []
    for process in process_iter():
        info = getattr(process, "info", {}) or {}
        name = str(info.get("name") or "").casefold()
        command = " ".join(str(part) for part in (info.get("cmdline") or ())).casefold()
        if name.startswith("jarvis") or any(
            marker in command
            for marker in (
                "jarvis.voice.production_runtime",
                "jarvis.runtime_supervisor",
                "jarvis.dev_supervisor",
                "jarvis-voice",
                "jarvis.app",
            )
        ):
            found.append(int(info.get("pid") or 0))
    return found


def _stamp() -> str:
    from uuid import uuid4

    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]


def retire_memory_files(
    data: Path, retire_to: Path, *, label: str = "memory"
) -> Path | None:
    """Move the memory files (only those) into a new folder; None if none exist."""
    data, retire_to = Path(data), Path(retire_to)
    present = [data / name for name in MEMORY_FILES if (data / name).exists()]
    if not present:
        return None
    if (
        retire_to.resolve() == data.resolve()
        or data.resolve() in retire_to.resolve().parents
    ):
        raise InitializationError("retired files must live outside the data folder")
    target = retire_to / f"{label}-retired-{_stamp()}"
    target.mkdir(parents=True, exist_ok=False)
    moved = []
    try:
        for path in present:
            path.replace(target / path.name)  # same volume: a rename, never a copy
            moved.append(path)
    except OSError as exc:
        # All or nothing: a half-moved set (e.g. a WAL left beside a new
        # database) must never exist. Put back what was moved.
        for path in reversed(moved):
            (target / path.name).replace(path)
        raise InitializationError(
            "memory files are in use or cannot be moved; nothing changed"
        ) from exc
    return target


def verify_memory_database(
    open_connection: Callable[[], Any], latest_version: int, *, expect_empty: bool
) -> dict:
    connection = open_connection()
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        foreign = connection.execute("PRAGMA foreign_key_check").fetchall()
        ledger = [
            int(row[0])
            for row in connection.execute(
                f"SELECT version FROM {_LEDGER} ORDER BY version"
            ).fetchall()
        ]
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        virtual = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND sql LIKE 'CREATE VIRTUAL TABLE%'"
            ).fetchall()
        ]
        rows = {}
        for name in tables:
            # The ledger records the migrations; FTS shadow tables hold index
            # configuration even when empty. Neither is memory content.
            if name == _LEDGER or any(name.startswith(v + "_") for v in virtual):
                continue
            quoted = '"' + name.replace('"', '""') + '"'
            rows[name] = int(
                connection.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]
            )
    finally:
        connection.close()
    nonempty = sorted(name for name, count in rows.items() if count)
    checks = {
        "latest_schema": version == latest_version,
        "ledger_complete": ledger == list(range(1, latest_version + 1)),
        "integrity_ok": integrity == ["ok"],
        "foreign_keys_ok": not foreign,
        "project_memory_tables_present": all(
            t in tables
            for t in (
                "conversation_workspace",
                "conversation_event",
                "conversation_event_fts",
            )
        ),
    }
    if expect_empty:
        checks["empty"] = not nonempty
    return {
        "verdict": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "schema_version": version,
        "latest_version": latest_version,
        "tables": len(tables),
        "nonempty_tables": nonempty,
    }


class _NoMigrationForTests:
    """Opens a database at its current version (tests and diagnostics only)."""

    def apply(self, connection: Any) -> int:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _production_opener(database: Path):
    from jarvis.memory.database import SqlCipherMemoryDatabaseFactory
    from jarvis.security.dpapi import WindowsDpapiKeyProtector

    factory = SqlCipherMemoryDatabaseFactory(
        database, key_protector=WindowsDpapiKeyProtector()
    )
    return factory.open  # SQLCipher verified, keyed, WAL, migrated


def main(argv=None, *, opener=None, processes=None) -> int:
    import argparse
    import os

    from jarvis.memory.migration_runner import MemoryMigrationRunner

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("initialize", "verify", "restore"))
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--retire-to", type=Path)
    parser.add_argument("--from", dest="source", type=Path)
    parser.add_argument("--expect-empty", action="store_true")
    args = parser.parse_args(argv)
    if opener is None and os.name != "nt":
        parser.error("needs Windows DPAPI and the SQLCipher runtime")
    data = args.data.resolve(strict=True)
    database = data / "memory.db"
    latest = MemoryMigrationRunner().latest_version
    open_connection = (opener or _production_opener)(database)

    if args.action in {"initialize", "restore"}:
        running = jarvis_processes(processes)
        if running:
            print(
                f"Jarvis is running (PIDs {running}); stop it first. Nothing changed."
            )
            return 2
        if args.retire_to is None:
            parser.error(f"{args.action} needs --retire-to")
    if args.action == "restore":
        if args.source is None or not (args.source / "memory.db").is_file():
            parser.error("restore needs --from <retired folder with memory.db>")
        aside = retire_memory_files(data, args.retire_to, label="memory-before-restore")
        for name in MEMORY_FILES:
            if (args.source / name).exists():
                (args.source / name).replace(data / name)
        print(
            f"Restored memory files from {args.source}; current set moved to {aside}."
        )
        return 0
    if args.action == "initialize":
        retired = retire_memory_files(data, args.retire_to)
        print(
            f"Previous memory files moved to {retired}"
            if retired
            else "No previous memory files; creating a new database."
        )
        if any((data / name).exists() for name in MEMORY_FILES):
            raise InitializationError("memory files still present after retirement")
    report = verify_memory_database(
        open_connection,
        latest,
        expect_empty=args.expect_empty or args.action == "initialize",
    )
    print(json.dumps(report, indent=2))
    print(f"Memory database: {report['verdict']}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
