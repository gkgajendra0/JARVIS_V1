"""Forget-time evidence scrub and residual check for personal memory.

docs/policy/personal-memory-evidence-retention.md: forgetting a fact deletes
its lineage and its own sources (with their quotes); any other personal-memory
quote that still names the forgotten item or an alias is then cleared (the
other fact is kept), and content-free learning outcomes for the same turns are
deleted. :func:`residual_report` then counts any personal-memory text store
that still holds a forgotten term. Diagnostic logs, backups and project
history rows are outside this check and are reported as retained elsewhere.
"""

from __future__ import annotations

import json
from uuid import uuid4

_MIN_TERM = 3


def _terms_from_value(raw: str | None) -> set[str]:
    try:
        value = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        value = raw
    terms = set()
    if isinstance(value, dict):
        for key in ("label", "value"):
            if isinstance(value.get(key), str):
                terms.add(value[key])
        for alias in value.get("aliases") or []:
            if isinstance(alias, str):
                terms.add(alias)
    elif isinstance(value, str):
        terms.add(value)
    return {t.strip() for t in terms if t and len(t.strip()) >= _MIN_TERM}


def collect_forget_targets(connection, assertion_ids) -> tuple[set[str], set[str]]:
    """Before deletion: the forgotten labels/values/aliases and turn refs."""
    ids = tuple(assertion_ids)
    if not ids:
        return set(), set()
    marks = ",".join("?" for _ in ids)
    terms: set[str] = set()
    refs: set[str] = set()
    for value_json, ref in connection.execute(
        f"SELECT a.value_json, s.canonical_ref FROM semantic_assertion a"
        f" LEFT JOIN memory_source s ON s.source_id = a.source_id"
        f" WHERE a.assertion_id IN ({marks})",
        ids,
    ):
        terms |= _terms_from_value(value_json)
        if ref:
            refs.add(ref)
    return terms, refs


def scrub_forgotten_evidence(connection, terms, refs, occurred_at) -> int:
    """After deletion: clear remaining quotes naming a forgotten term (the
    fact itself stays) and delete content-free outcomes for the same turns.
    Returns the number of quotes cleared."""
    wanted = [t.casefold() for t in terms if t]
    cleared = 0
    if wanted:
        rows = connection.execute(
            "SELECT source_id, evidence_text FROM memory_source"
            " WHERE evidence_text IS NOT NULL"
        ).fetchall()
        for source_id, text in rows:
            if any(term in text.casefold() for term in wanted):
                connection.execute(
                    "UPDATE memory_source SET evidence_text = NULL WHERE source_id = ?",
                    (source_id,),
                )
                connection.execute(
                    "INSERT INTO memory_operation (operation_id, operation_type,"
                    " target_kind, target_id, source_id, occurred_at, reason_code,"
                    " result_state, content_fingerprint) VALUES (?, 'forget',"
                    " 'memory_source', ?, NULL, ?, 'evidence_removed_by_forget',"
                    " 'evidence_removed', NULL)",
                    (str(uuid4()), source_id, occurred_at),
                )
                cleared += 1
    for ref in refs:
        connection.execute(
            "DELETE FROM personal_learning_outcome WHERE source_turn_ref = ?", (ref,)
        )
    return cleared


def _like_count(connection, sql, terms) -> int:
    total = 0
    for term in terms:
        pattern = "%" + term.casefold().replace("%", "").replace("_", "") + "%"
        total += connection.execute(sql, (pattern,)).fetchone()[0]
    return total


def residual_report(connection, terms) -> dict[str, int]:
    """Counts of forgotten terms still present in personal-memory text stores.

    All zeros means no recoverable copy remains in personal memory. Logs,
    backups and project history are not personal-memory stores and are not
    covered here (see the retention policy)."""
    terms = sorted({t for t in terms if t and len(t) >= _MIN_TERM})
    fts = 0
    for term in terms:
        phrase = '"' + term.replace('"', " ") + '"'
        try:
            fts += connection.execute(
                "SELECT count(*) FROM semantic_assertion_fts"
                " WHERE semantic_assertion_fts MATCH ?",
                (phrase,),
            ).fetchone()[0]
        except Exception:  # noqa: BLE001 - unparseable phrase is reported, not hidden
            fts += 1
    return {
        "assertion_value": _like_count(
            connection,
            "SELECT count(*) FROM semantic_assertion WHERE lower(value_json) LIKE ?",
            terms,
        ),
        "assertion_text": _like_count(
            connection,
            "SELECT count(*) FROM semantic_assertion WHERE lower(normalized_text) LIKE ?",
            terms,
        ),
        "search_index": fts,
        "orphan_embeddings": connection.execute(
            "SELECT count(*) FROM semantic_assertion_embedding e WHERE NOT EXISTS"
            " (SELECT 1 FROM semantic_assertion a WHERE a.assertion_id = e.assertion_id)"
        ).fetchone()[0],
        "evidence_quotes": _like_count(
            connection,
            "SELECT count(*) FROM memory_source WHERE lower(evidence_text) LIKE ?",
            terms,
        ),
        "learning_outcomes": _like_count(
            connection,
            "SELECT count(*) FROM personal_learning_outcome WHERE"
            " lower(category_key || ' ' || reason_code || ' ' || source_turn_ref) LIKE ?",
            terms,
        ),
        "topic_checkpoints": _like_count(
            connection,
            "SELECT count(*) FROM conversation_topic_checkpoint"
            " WHERE lower(state_json) LIKE ?",
            terms,
        ),
    }
