-- Personal memory slice 1 (design revision 2, 2026-11-20).
--
-- 1. A `refine` lifecycle operation: a later statement adds or sharpens detail
--    of a fact that was true but less complete ("I bought the Tigor in March
--    2017" after "I have a Tigor"). Only Jarvis's belief changes, not the world:
--    the earlier row is superseded in system time with its validity untouched
--    and is never retracted (which would mean it was false). The operation
--    type list is a CHECK constraint, so the table is rebuilt; every existing
--    row is copied unchanged and the index is recreated. Nothing references
--    memory_operation, and no trigger or view reads it.
-- 2. A content-free record of learning candidates that were not saved, with
--    the reason. It holds no label, value or quote: only which turn, which
--    candidate ordinal, the category key and a reason code.
--
-- Rolling back the code alone does not reverse this migration: older code
-- refuses a schema-8 database (MemorySchemaTooNewError). The clean rollback is
-- restoring the pre-install database copy together with the older code.

CREATE TABLE memory_operation_v8 (
    operation_id TEXT PRIMARY KEY,
    operation_type TEXT NOT NULL CHECK (
        operation_type IN (
            'create',
            'historical_change',
            'correct',
            'retract',
            'verify',
            'expire',
            'forget',
            'refine'
        )
    ),
    target_kind TEXT NOT NULL,
    target_id TEXT,
    source_id TEXT REFERENCES memory_source(source_id) ON DELETE SET NULL,
    occurred_at TEXT NOT NULL,
    reason_code TEXT,
    result_state TEXT NOT NULL,
    content_fingerprint TEXT CHECK (
        content_fingerprint IS NULL OR length(content_fingerprint) = 64
    )
);

INSERT INTO memory_operation_v8 (
    operation_id,
    operation_type,
    target_kind,
    target_id,
    source_id,
    occurred_at,
    reason_code,
    result_state,
    content_fingerprint
)
SELECT
    operation_id,
    operation_type,
    target_kind,
    target_id,
    source_id,
    occurred_at,
    reason_code,
    result_state,
    content_fingerprint
FROM memory_operation
ORDER BY rowid;

DROP TABLE memory_operation;

ALTER TABLE memory_operation_v8 RENAME TO memory_operation;

CREATE INDEX idx_memory_operation_target
ON memory_operation(target_kind, target_id, occurred_at);

CREATE TABLE personal_learning_outcome (
    receipt_id TEXT NOT NULL,
    source_turn_ref TEXT NOT NULL,
    candidate_ordinal INTEGER NOT NULL CHECK (candidate_ordinal >= 0),
    category_key TEXT NOT NULL,
    reason_code TEXT NOT NULL CHECK (
        length(reason_code) BETWEEN 1 AND 64
        AND reason_code NOT GLOB '*[^a-z0-9_]*'
    ),
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (receipt_id, candidate_ordinal)
) WITHOUT ROWID;

CREATE INDEX idx_personal_learning_outcome_turn
ON personal_learning_outcome(source_turn_ref);
