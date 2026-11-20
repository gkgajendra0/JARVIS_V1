"""Migration 0008 (refine operation + content-free learning outcomes) upgrading
a populated schema-7 database: every existing row survives unchanged, the
rebuilt operation table keeps its constraints and index, and older code
refuses the migrated database (a code-only rollback does not work)."""

from __future__ import annotations

import hashlib
import re
import sqlite3

import pytest

from jarvis.memory.migration_runner import (
    MemoryMigrationRunner,
    MemorySchemaTooNewError,
    discover_memory_migrations,
)

T0 = "2026-11-01T05:00:00Z"
T1 = "2026-11-10T05:00:00Z"
OPERATION_TYPES = (
    "create",
    "historical_change",
    "correct",
    "retract",
    "verify",
    "expire",
    "forget",
)


def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA secure_delete = ON")
    return conn


def schema7() -> sqlite3.Connection:
    conn = connection()
    assert MemoryMigrationRunner(discover_memory_migrations()[:7]).apply(conn) == 7
    return conn


def populate(conn: sqlite3.Connection) -> None:
    for index in range(3):
        conn.execute(
            "INSERT INTO memory_source (source_id, source_class, canonical_ref,"
            " observed_at, authority_class, sensitivity, evidence_text,"
            " evidence_hash, created_at) VALUES (?, 'owner_direct', ?, ?,"
            " 'owner_direct', 'standard', ?, ?, ?)",
            (
                f"source-{index}",
                f"conversation:s:turn:t{index}",
                T0,
                f"fictional evidence {index}",
                hashlib.sha256(str(index).encode()).hexdigest(),
                T0,
            ),
        )
    states = [
        ("a-active", "active", None, None),
        ("a-superseded", "superseded", T1, T1),
        ("a-retracted", "retracted", None, T1),
        ("a-expired", "expired", T1, T1),
    ]
    for assertion_id, state, valid_to, system_to in states:
        conn.execute(
            "INSERT INTO semantic_assertion (assertion_id, subject_scope, subject,"
            " predicate, value_type, value_json, normalized_text, source_id,"
            " valid_from, valid_to, system_from, system_to, state,"
            " verification_state, confidence, freshness_class, sensitivity,"
            " created_at, updated_at) VALUES (?, 'personal', 'owner', ?, 'json',"
            " ?, ?, 'source-0', NULL, ?, ?, ?, ?, 'unverified', 0.9,"
            " 'changeable', 'standard', ?, ?)",
            (
                assertion_id,
                f"owned_item_{assertion_id}",
                (
                    '{"schema":"personal-learning-v1","category":"owned_item",'
                    '"kind":"vehicle","label":"Tigor","value":"Tigor","state":"owned"}'
                ),
                f"owned_item.vehicle: Tigor ({state})",
                valid_to,
                T0,
                system_to,
                state,
                T0,
                T0,
            ),
        )
    conn.execute(
        "INSERT INTO semantic_assertion_embedding (assertion_id, model_id,"
        " model_revision, dimension, dtype, byte_order, normalized, content_sha256,"
        " embedding_blob, created_at, updated_at) VALUES ('a-active',"
        " 'fictional-model', 'r1', 2, 'float32', 'little', 1, ?, ?, ?, ?)",
        (hashlib.sha256(b"x").hexdigest(), b"\x00" * 8, T0, T0),
    )
    for index, operation_type in enumerate(OPERATION_TYPES):
        conn.execute(
            "INSERT INTO memory_operation (operation_id, operation_type,"
            " target_kind, target_id, source_id, occurred_at, reason_code,"
            " result_state, content_fingerprint) VALUES (?, ?, 'semantic_assertion',"
            " 'a-active', ?, ?, ?, 'active', ?)",
            (
                f"op-{index}",
                operation_type,
                f"source-{index % 3}" if index != 6 else None,
                T0,
                "automatic_learning" if index % 2 else None,
                hashlib.sha256(operation_type.encode()).hexdigest()
                if index % 3 == 0
                else None,
            ),
        )
    conn.execute(
        "INSERT INTO personal_learning_receipt VALUES"
        " ('runtime', 't0', 0, 'personal-learning-v1', 'owned_item.vehicle', ?,"
        " 'source-0', 'a-active')",
        ("0" * 64,),
    )
    conn.execute(
        "INSERT INTO personal_learning_suppression VALUES ('plan', 2, 0, ?)", (T0,)
    )
    conn.commit()


def table_digests(conn: sqlite3.Connection) -> dict[str, str]:
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%' AND name != 'jarvis_schema_migration'"
            " ORDER BY name"
        )
    ]
    digests = {}
    for name in names:
        columns = [r[1] for r in conn.execute(f'PRAGMA table_info("{name}")')]
        order = ", ".join(f'"{c}"' for c in columns)
        rows = conn.execute(f'SELECT * FROM "{name}" ORDER BY {order}').fetchall()
        digests[name] = hashlib.sha256(repr(rows).encode()).hexdigest()
    return digests


def operation_sql(conn: sqlite3.Connection) -> str:
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_operation'"
    ).fetchone()[0]
    return re.sub(r"\s+", " ", sql.replace('"', "")).strip()


def test_upgrade_from_populated_schema_7_preserves_every_row() -> None:
    conn = schema7()
    populate(conn)
    before = table_digests(conn)
    operations_before = conn.execute(
        "SELECT * FROM memory_operation ORDER BY operation_id"
    ).fetchall()
    sql_before = operation_sql(conn)

    assert MemoryMigrationRunner().apply(conn) == 8

    after = table_digests(conn)
    assert set(after) == set(before) | {"personal_learning_outcome"}
    assert {k: after[k] for k in before} == before
    assert (
        conn.execute("SELECT * FROM memory_operation ORDER BY operation_id").fetchall()
        == operations_before
    )
    assert conn.execute(
        "SELECT count(*) FROM personal_learning_outcome"
    ).fetchone() == (0,)
    assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    # The only definition change is the added 'refine' operation type.
    rebuilt = operation_sql(conn)
    assert rebuilt.replace(", 'refine'", "") == sql_before
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
        " AND name='idx_memory_operation_target' AND tbl_name='memory_operation'"
    ).fetchone() == ("idx_memory_operation_target",)


def test_rebuilt_operation_table_keeps_its_constraints() -> None:
    conn = schema7()
    populate(conn)
    MemoryMigrationRunner().apply(conn)
    conn.execute(
        "INSERT INTO memory_operation (operation_id, operation_type, target_kind,"
        " occurred_at, result_state) VALUES ('op-refine', 'refine',"
        " 'semantic_assertion', ?, 'active')",
        (T1,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO memory_operation (operation_id, operation_type, target_kind,"
            " occurred_at, result_state) VALUES ('op-bad', 'rewrite',"
            " 'semantic_assertion', ?, 'active')",
            (T1,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO memory_operation (operation_id, operation_type, target_kind,"
            " occurred_at, result_state, content_fingerprint) VALUES ('op-fp',"
            " 'verify', 'semantic_assertion', ?, 'active', 'short')",
            (T1,),
        )
    # ON DELETE SET NULL to memory_source still holds after the rebuild.
    conn.execute("DELETE FROM memory_operation WHERE source_id='source-2'")
    conn.execute(
        "INSERT INTO memory_operation (operation_id, operation_type, target_kind,"
        " source_id, occurred_at, result_state) VALUES ('op-src', 'verify',"
        " 'semantic_assertion', 'source-2', ?, 'active')",
        (T1,),
    )
    conn.execute("DELETE FROM memory_source WHERE source_id='source-2'")
    assert conn.execute(
        "SELECT source_id FROM memory_operation WHERE operation_id='op-src'"
    ).fetchone() == (None,)


def test_learning_outcome_record_is_content_free() -> None:
    conn = connection()
    MemoryMigrationRunner().apply(conn)
    columns = [
        r[1] for r in conn.execute("PRAGMA table_info(personal_learning_outcome)")
    ]
    assert columns == [
        "receipt_id",
        "source_turn_ref",
        "candidate_ordinal",
        "category_key",
        "reason_code",
        "recorded_at",
    ]
    conn.execute(
        "INSERT INTO personal_learning_outcome VALUES"
        " ('r1', 'conversation:s:turn:t1', 0, 'plan', 'catalog_page_ambiguous', ?)",
        (T1,),
    )
    for reason in ("Has Spaces", "I own a Tigor", "", "x" * 65):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO personal_learning_outcome VALUES"
                " ('r2', 'conversation:s:turn:t1', 1, 'plan', ?, ?)",
                (reason, T1),
            )


def test_older_code_refuses_the_migrated_database() -> None:
    """Rollback compatibility: reverting the code alone does not reverse 0008."""
    conn = schema7()
    populate(conn)
    MemoryMigrationRunner().apply(conn)
    with pytest.raises(MemorySchemaTooNewError):
        MemoryMigrationRunner(discover_memory_migrations()[:7]).apply(conn)


def test_a_failed_upgrade_leaves_schema_7_intact() -> None:
    conn = schema7()
    populate(conn)
    before = table_digests(conn)
    # An existing table with the new name makes 0008 fail inside its transaction.
    conn.execute("CREATE TABLE personal_learning_outcome (x)")
    conn.commit()
    with pytest.raises(Exception, match="0008"):
        MemoryMigrationRunner().apply(conn)
    assert conn.execute("PRAGMA user_version").fetchone() == (7,)
    after = table_digests(conn)
    after.pop("personal_learning_outcome")
    assert after == before
    assert "'refine'" not in operation_sql(conn)
    assert (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='memory_operation_v8'"
        ).fetchone()
        is None
    )
