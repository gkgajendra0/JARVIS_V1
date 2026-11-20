"""Memory migration rehearsal on isolated copies (numbers only, no content).

Run with the Jarvis virtual environment and the code under test on PYTHONPATH.
The PowerShell wrapper ``tools/windows/Test-JarvisMemoryMigrationCopy.ps1``
drives it; it never touches the live database except to read and hash it.

Commands (each prints one JSON object; no labels, values or text):

- ``inspect DB``: read-only open (no migrations, no WAL setup): schema version,
  migration ledger names, and per-table row counts and content digests.
- ``migrate DB``: normal open, which applies pending migrations, then the same
  inventory plus ``integrity_check`` and ``foreign_key_check``.
- ``open DB``: normal open with whatever code is on PYTHONPATH; reports the
  resulting version or the error class (used to show older code refuses a
  newer schema, and that a restored copy opens).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SKIP_TABLES = ("sqlite_",)


def table_inventory(connection) -> dict[str, dict[str, object]]:
    names = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        if not str(row[0]).startswith(SKIP_TABLES)
    ]
    inventory = {}
    for name in names:
        columns = [r[1] for r in connection.execute(f'PRAGMA table_info("{name}")')]
        order = ", ".join(f'"{c}"' for c in columns)
        rows = connection.execute(f'SELECT * FROM "{name}" ORDER BY {order}').fetchall()
        inventory[name] = {
            "rows": len(rows),
            "digest": hashlib.sha256(repr(rows).encode()).hexdigest(),
        }
    return inventory


def summary(connection) -> dict[str, object]:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    ledger = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM jarvis_schema_migration ORDER BY version"
        )
    ]
    return {
        "user_version": version,
        "ledger": ledger,
        "tables": table_inventory(connection),
    }


def compare(before: dict, after: dict, *, changed_definition=("memory_operation",)):
    """Tables present before must keep identical rows; report what differs."""
    differing = sorted(
        name
        for name, stats in before["tables"].items()
        if name != "jarvis_schema_migration" and after["tables"].get(name) != stats
    )
    added = sorted(set(after["tables"]) - set(before["tables"]))
    return {
        "differing_tables": differing,
        "added_tables": added,
        "only_expected_definition_changes": differing == [],
        "definition_rebuilt": list(changed_definition),
    }


def _protector():
    from jarvis.security.dpapi import WindowsDpapiKeyProtector

    return WindowsDpapiKeyProtector()


def inspect(path: Path) -> dict:
    from jarvis.memory.database import open_existing_memory_database_read_only

    connection = open_existing_memory_database_read_only(
        path, key_protector=_protector()
    )
    try:
        return summary(connection)
    finally:
        connection.close()


def migrate(path: Path) -> dict:
    from jarvis.memory.database import SqlCipherMemoryDatabaseFactory

    connection = SqlCipherMemoryDatabaseFactory(path, key_protector=_protector()).open()
    try:
        result = summary(connection)
        result["integrity_check"] = [
            r[0] for r in connection.execute("PRAGMA integrity_check")
        ]
        result["foreign_key_violations"] = len(
            connection.execute("PRAGMA foreign_key_check").fetchall()
        )
        return result
    finally:
        connection.close()


def open_with_current_code(path: Path) -> dict:
    from jarvis.memory.database import SqlCipherMemoryDatabaseFactory

    try:
        connection = SqlCipherMemoryDatabaseFactory(
            path, key_protector=_protector()
        ).open()
    except Exception as exc:  # noqa: BLE001 - reported by class name only
        return {"opened": False, "error": type(exc).__name__}
    try:
        return {"opened": True, **summary(connection)}
    finally:
        connection.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "migrate", "open"))
    parser.add_argument("database", type=Path)
    args = parser.parse_args(argv)
    path = args.database.resolve()
    if not path.is_file():
        parser.error("database copy not found")
    action = {"inspect": inspect, "migrate": migrate, "open": open_with_current_code}
    print(json.dumps(action[args.command](path), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
