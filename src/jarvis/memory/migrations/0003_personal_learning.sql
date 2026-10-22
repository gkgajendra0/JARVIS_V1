CREATE TABLE personal_learning_receipt (
    runtime_id TEXT NOT NULL,
    source_turn_id TEXT NOT NULL,
    candidate_ordinal INTEGER NOT NULL,
    policy_version TEXT NOT NULL,
    category TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    PRIMARY KEY(source_turn_id, candidate_ordinal, policy_version)
);
CREATE TABLE personal_learning_suppression (
    category TEXT PRIMARY KEY,
    epoch INTEGER NOT NULL CHECK(epoch >= 0),
    suppressed INTEGER NOT NULL CHECK(suppressed IN (0,1)),
    updated_at TEXT NOT NULL
);
