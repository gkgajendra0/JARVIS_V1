"""Research-only Step 4 SQLite temporal/FTS bake-off.

This file is deliberately outside ``src/jarvis``.  It does not implement runtime
memory.  It tests whether mature SQLite primitives are sufficient for the
canonical-memory mechanics JARVIS needs before a heavier database is adopted.

Run from the repository root with Python 3.11+::

    python tools/research/step4_memory_sqlite_bakeoff.py

The output is JSON so results from the real JARVIS Windows machine can be copied
into the research record without depending on this development environment.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path

SEED_SIZE = 30_000
SYSTEM_T0 = "2026-09-01T10:00:00+00:00"
SYSTEM_T1 = "2027-01-10T10:00:00+00:00"
SYSTEM_T2 = "2027-02-01T10:00:00+00:00"


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE source (
    source_id TEXT PRIMARY KEY,
    source_class TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    authority_rank INTEGER NOT NULL,
    source_ref TEXT
);

CREATE TABLE fact_version (
    version_id TEXT PRIMARY KEY,
    fact_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    value_text TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'retracted')),
    valid_from TEXT,
    valid_to TEXT,
    system_from TEXT NOT NULL,
    system_to TEXT,
    last_verified_at TEXT,
    source_id TEXT NOT NULL REFERENCES source(source_id),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1)
);

CREATE INDEX fact_exact_current_idx
    ON fact_version(subject, predicate, system_to, valid_to, status);

CREATE INDEX fact_id_temporal_idx
    ON fact_version(fact_id, system_from, system_to, valid_from, valid_to);

-- Research-derived index only.  Canonical truth remains fact_version.
CREATE VIRTUAL TABLE fact_fts USING fts5(
    version_id UNINDEXED,
    subject,
    predicate,
    value_text,
    tokenize='unicode61'
);
"""


AS_OF_SQL = """
SELECT value_text, valid_from, valid_to, system_from, system_to
FROM fact_version
WHERE fact_id = ?
  AND system_from <= ?
  AND (system_to IS NULL OR system_to > ?)
  AND (valid_from IS NULL OR valid_from <= ?)
  AND (valid_to IS NULL OR valid_to > ?)
  AND status = 'active'
ORDER BY system_from DESC
LIMIT 1
"""


CURRENT_SQL = """
SELECT value_text
FROM fact_version
WHERE subject = ?
  AND predicate = ?
  AND system_to IS NULL
  AND valid_to IS NULL
  AND status = 'active'
LIMIT 10
"""


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    if str(journal_mode).lower() != "wal":
        raise RuntimeError(f"expected WAL mode, got {journal_mode!r}")
    connection.executescript(SCHEMA)
    return connection


def _insert_source(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    observed_at: str,
    source_ref: str,
) -> None:
    connection.execute(
        "INSERT INTO source VALUES (?, 'explicit_user', ?, 100, ?)",
        (source_id, observed_at, source_ref),
    )


def _insert_fact(
    connection: sqlite3.Connection,
    *,
    version_id: str,
    fact_id: str,
    subject: str,
    predicate: str,
    value: str,
    source_id: str,
    system_from: str,
    valid_from: str | None,
    valid_to: str | None = None,
    status: str = "active",
) -> None:
    connection.execute(
        """
        INSERT INTO fact_version(
            version_id, fact_id, subject, predicate, value_text, status,
            valid_from, valid_to, system_from, system_to, last_verified_at,
            source_id, confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 1.0)
        """,
        (
            version_id,
            fact_id,
            subject,
            predicate,
            value,
            status,
            valid_from,
            valid_to,
            system_from,
            system_from,
            source_id,
        ),
    )
    connection.execute(
        "INSERT INTO fact_fts(version_id, subject, predicate, value_text) "
        "VALUES (?, ?, ?, ?)",
        (version_id, subject, predicate, value),
    )


def _as_of(
    connection: sqlite3.Connection,
    *,
    fact_id: str,
    valid_time: str,
    system_time: str,
) -> str | None:
    row = connection.execute(
        AS_OF_SQL,
        (fact_id, system_time, system_time, valid_time, valid_time),
    ).fetchone()
    return None if row is None else str(row["value_text"])


def _assert_temporal_semantics(connection: sqlite3.Connection) -> dict[str, bool]:
    """Exercise historical change and later correction semantics.

    Scenario 1 is a real-world change: 235/75 R15 was true and later changed to
    215/75 R15.  Scenario 2 is a correction: JARVIS originally learned an
    incorrect value and later learns what had actually been true all along.
    """

    _insert_source(
        connection,
        source_id="source-tyre-1",
        observed_at=SYSTEM_T0,
        source_ref="turn-1",
    )
    _insert_fact(
        connection,
        version_id="tyre-v1",
        fact_id="jimny-tyre-preference",
        subject="gajendra",
        predicate="jimny.preferred_tyre_size",
        value="235/75 R15",
        source_id="source-tyre-1",
        system_from=SYSTEM_T0,
        valid_from="2026-09-01T00:00:00+00:00",
    )

    # At T1 the preference genuinely changes.  System-close the old belief,
    # then record the now-known valid end plus the new current value.
    connection.execute(
        "UPDATE fact_version SET system_to = ? WHERE version_id = 'tyre-v1'",
        (SYSTEM_T1,),
    )
    connection.execute("DELETE FROM fact_fts WHERE version_id = 'tyre-v1'")
    _insert_source(
        connection,
        source_id="source-tyre-2",
        observed_at=SYSTEM_T1,
        source_ref="turn-2",
    )
    _insert_fact(
        connection,
        version_id="tyre-v1-revised",
        fact_id="jimny-tyre-preference",
        subject="gajendra",
        predicate="jimny.preferred_tyre_size",
        value="235/75 R15",
        source_id="source-tyre-2",
        system_from=SYSTEM_T1,
        valid_from="2026-09-01T00:00:00+00:00",
        valid_to="2027-01-10T00:00:00+00:00",
    )
    _insert_fact(
        connection,
        version_id="tyre-v2",
        fact_id="jimny-tyre-preference",
        subject="gajendra",
        predicate="jimny.preferred_tyre_size",
        value="215/75 R15",
        source_id="source-tyre-2",
        system_from=SYSTEM_T1,
        valid_from="2027-01-10T00:00:00+00:00",
    )

    # Correction scenario: an old belief was wrong rather than historically true.
    _insert_source(
        connection,
        source_id="source-city-1",
        observed_at=SYSTEM_T0,
        source_ref="turn-3",
    )
    _insert_fact(
        connection,
        version_id="city-v1",
        fact_id="home-city",
        subject="gajendra",
        predicate="home.city",
        value="Bhopal",
        source_id="source-city-1",
        system_from=SYSTEM_T0,
        valid_from="2026-01-01T00:00:00+00:00",
    )
    connection.execute(
        "UPDATE fact_version SET system_to = ? WHERE version_id = 'city-v1'",
        (SYSTEM_T1,),
    )
    connection.execute("DELETE FROM fact_fts WHERE version_id = 'city-v1'")
    _insert_source(
        connection,
        source_id="source-city-2",
        observed_at=SYSTEM_T1,
        source_ref="turn-4",
    )
    _insert_fact(
        connection,
        version_id="city-v2",
        fact_id="home-city",
        subject="gajendra",
        predicate="home.city",
        value="Sagar",
        source_id="source-city-2",
        system_from=SYSTEM_T1,
        valid_from="2026-01-01T00:00:00+00:00",
    )
    connection.commit()

    results = {
        "old_system_knew_old_tyre": _as_of(
            connection,
            fact_id="jimny-tyre-preference",
            valid_time="2026-12-01T00:00:00+00:00",
            system_time="2026-12-01T00:00:00+00:00",
        )
        == "235/75 R15",
        "current_system_knows_historical_tyre": _as_of(
            connection,
            fact_id="jimny-tyre-preference",
            valid_time="2026-12-01T00:00:00+00:00",
            system_time=SYSTEM_T2,
        )
        == "235/75 R15",
        "current_system_knows_current_tyre": _as_of(
            connection,
            fact_id="jimny-tyre-preference",
            valid_time=SYSTEM_T2,
            system_time=SYSTEM_T2,
        )
        == "215/75 R15",
        "old_system_exposes_pre_correction_belief": _as_of(
            connection,
            fact_id="home-city",
            valid_time="2026-06-01T00:00:00+00:00",
            system_time="2026-12-01T00:00:00+00:00",
        )
        == "Bhopal",
        "current_system_uses_corrected_history": _as_of(
            connection,
            fact_id="home-city",
            valid_time="2026-06-01T00:00:00+00:00",
            system_time=SYSTEM_T2,
        )
        == "Sagar",
    }
    if not all(results.values()):
        raise AssertionError(f"temporal semantics failed: {results}")
    return results


def _seed_retrieval_corpus(connection: sqlite3.Connection, count: int) -> float:
    values = (
        "Jimny preferred tyre size 235/75 R15",
        "wake detector false positive when TV audio is loud",
        "रिसर्च पहले करना है फिर implementation",
        "Jarvis ko pehle existing technology research karni chahiye",
        "owner prefers local privacy-aware memory",
        "camera is DJI Osmo Pocket 3",
        "project uses LiveKit realtime voice",
        "step 4 covers personal and episodic memory",
    )
    source_id = "seed-source"
    _insert_source(
        connection,
        source_id=source_id,
        observed_at=SYSTEM_T0,
        source_ref="synthetic-benchmark",
    )
    rows: list[tuple[object, ...]] = []
    fts_rows: list[tuple[str, str, str, str]] = []
    for index in range(count):
        version_id = f"seed-v-{index}"
        subject = f"subject_{index % 200}"
        predicate = f"predicate_{index % 500}"
        value = f"{values[index % len(values)]} item {index}"
        rows.append(
            (
                version_id,
                f"seed-f-{index}",
                subject,
                predicate,
                value,
                "active",
                "2026-01-01T00:00:00+00:00",
                None,
                SYSTEM_T0,
                None,
                SYSTEM_T0,
                source_id,
                1.0,
            )
        )
        fts_rows.append((version_id, subject, predicate, value))

    started = time.perf_counter()
    connection.executemany(
        "INSERT INTO fact_version VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.executemany(
        "INSERT INTO fact_fts(version_id, subject, predicate, value_text) "
        "VALUES (?, ?, ?, ?)",
        fts_rows,
    )
    connection.commit()
    return time.perf_counter() - started


def _latency_ms(action, *, loops: int) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(loops):
        started = time.perf_counter_ns()
        action()
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    samples.sort()
    p95_index = min(len(samples) - 1, int(len(samples) * 0.95))
    return {
        "p50_ms": round(statistics.median(samples), 4),
        "p95_ms": round(samples[p95_index], 4),
        "max_ms": round(max(samples), 4),
    }


def _fts_count(connection: sqlite3.Connection, query: str) -> int:
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM fact_fts WHERE fact_fts MATCH ?",
            (query,),
        ).fetchone()[0]
    )


def _test_forget_path(connection: sqlite3.Connection) -> dict[str, object]:
    """Verify canonical + derived retrieval deletion for one isolated memory."""

    _insert_source(
        connection,
        source_id="forget-source",
        observed_at=SYSTEM_T2,
        source_ref="turn-forget",
    )
    _insert_fact(
        connection,
        version_id="forget-v1",
        fact_id="forget-fact",
        subject="gajendra",
        predicate="temporary.secretless_test",
        value="ORCHID-NEBULA-8842",
        source_id="forget-source",
        system_from=SYSTEM_T2,
        valid_from=SYSTEM_T2,
    )
    connection.commit()
    before = _fts_count(connection, '"ORCHID-NEBULA-8842"')

    # Explicit forget is physical erasure of canonical content and derived index.
    connection.execute("DELETE FROM fact_fts WHERE version_id = 'forget-v1'")
    connection.execute("DELETE FROM fact_version WHERE fact_id = 'forget-fact'")
    connection.execute("DELETE FROM source WHERE source_id = 'forget-source'")
    connection.commit()

    after_fts = _fts_count(connection, '"ORCHID-NEBULA-8842"')
    after_canonical = int(
        connection.execute(
            "SELECT COUNT(*) FROM fact_version WHERE fact_id = 'forget-fact'"
        ).fetchone()[0]
    )
    if before != 1 or after_fts != 0 or after_canonical != 0:
        raise AssertionError("forget-path zero-recall assertion failed")
    return {
        "before_delete_fts_hits": before,
        "after_delete_fts_hits": after_fts,
        "after_delete_canonical_rows": after_canonical,
    }


def _secure_delete_support(connection: sqlite3.Connection) -> dict[str, object]:
    try:
        connection.execute(
            "INSERT INTO fact_fts(fact_fts, rank) VALUES('secure-delete', 1)"
        )
    except sqlite3.DatabaseError as exc:
        return {"supported": False, "detail": str(exc)}
    return {"supported": True, "detail": "enabled for research FTS table"}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="jarvis-step4-") as directory:
        db_path = Path(directory) / "memory-bakeoff.sqlite3"
        connection = _connect(db_path)
        try:
            temporal = _assert_temporal_semantics(connection)
            secure_delete = _secure_delete_support(connection)
            seed_seconds = _seed_retrieval_corpus(connection, SEED_SIZE)

            exact = _latency_ms(
                lambda: connection.execute(
                    CURRENT_SQL,
                    ("subject_42", "predicate_42"),
                ).fetchall(),
                loops=500,
            )
            fts_english = _latency_ms(
                lambda: connection.execute(
                    "SELECT version_id, bm25(fact_fts) AS score FROM fact_fts "
                    "WHERE fact_fts MATCH ? ORDER BY score LIMIT 10",
                    ('"wake detector" TV',),
                ).fetchall(),
                loops=200,
            )
            fts_hindi = _latency_ms(
                lambda: connection.execute(
                    "SELECT version_id, bm25(fact_fts) AS score FROM fact_fts "
                    "WHERE fact_fts MATCH ? ORDER BY score LIMIT 10",
                    ("रिसर्च implementation",),
                ).fetchall(),
                loops=200,
            )
            fts_hinglish = _latency_ms(
                lambda: connection.execute(
                    "SELECT version_id, bm25(fact_fts) AS score FROM fact_fts "
                    "WHERE fact_fts MATCH ? ORDER BY score LIMIT 10",
                    ("existing technology Jarvis",),
                ).fetchall(),
                loops=200,
            )
            forget = _test_forget_path(connection)

            report = {
                "status": "PASS",
                "purpose": "research-only; not a production architecture approval",
                "python_sqlite_version": sqlite3.sqlite_version,
                "seed_records": SEED_SIZE,
                "seed_seconds": round(seed_seconds, 4),
                "temporal_semantics": temporal,
                "fts_secure_delete": secure_delete,
                "latency": {
                    "exact_current_fact": exact,
                    "fts_english": fts_english,
                    "fts_hindi": fts_hindi,
                    "fts_hinglish": fts_hinglish,
                },
                "forget_zero_recall": forget,
                "database_bytes": db_path.stat().st_size,
            }
            print(json.dumps(report, indent=2, ensure_ascii=False))
        finally:
            connection.close()


if __name__ == "__main__":
    main()
