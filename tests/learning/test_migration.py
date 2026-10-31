import sqlite3

from jarvis.memory.migration_runner import (
    MemoryMigrationRunner,
    discover_memory_migrations,
)


def test_schema_two_upgrades_atomically_without_changing_prior_migration_hashes():
    c = sqlite3.connect(":memory:")
    migrations = discover_memory_migrations()
    MemoryMigrationRunner(migrations[:2]).apply(c)
    prior = c.execute(
        "SELECT version,sha256 FROM jarvis_schema_migration ORDER BY version"
    ).fetchall()
    assert MemoryMigrationRunner().apply(c) == 5
    assert (
        c.execute(
            "SELECT version,sha256 FROM jarvis_schema_migration WHERE version<=2 ORDER BY version"
        ).fetchall()
        == prior
    )
    assert (
        c.execute("SELECT count(*) FROM personal_learning_receipt").fetchone()[0] == 0
    )
    assert (
        c.execute("SELECT count(*) FROM personal_learning_suppression").fetchone()[0]
        == 0
    )
