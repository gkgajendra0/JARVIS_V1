CREATE TABLE jarvis_schema_migration (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    name TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    applied_at TEXT NOT NULL
);

CREATE TABLE memory_source (
    source_id TEXT PRIMARY KEY,
    source_class TEXT NOT NULL CHECK (
        source_class IN (
            'owner_explicit',
            'owner_direct',
            'reflection',
            'assistant_output',
            'external_web',
            'external_email',
            'external_file',
            'runtime_config',
            'repository',
            'tool'
        )
    ),
    canonical_ref TEXT NOT NULL,
    source_created_at TEXT,
    observed_at TEXT NOT NULL,
    authority_class TEXT NOT NULL CHECK (
        authority_class IN (
            'owner_explicit',
            'owner_direct',
            'authoritative_runtime',
            'verified',
            'inferred',
            'untrusted'
        )
    ),
    sensitivity TEXT NOT NULL CHECK (
        sensitivity IN ('standard', 'private', 'local_only', 'secret_prohibited')
    ),
    evidence_text TEXT,
    evidence_hash TEXT CHECK (evidence_hash IS NULL OR length(evidence_hash) = 64),
    external_ref TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE semantic_assertion (
    assertion_rowid INTEGER PRIMARY KEY,
    assertion_id TEXT NOT NULL UNIQUE,
    subject_scope TEXT NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    value_type TEXT NOT NULL CHECK (
        value_type IN ('text', 'number', 'boolean', 'json')
    ),
    value_json TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES memory_source(source_id) ON DELETE RESTRICT,
    valid_from TEXT,
    valid_to TEXT,
    system_from TEXT NOT NULL,
    system_to TEXT,
    last_verified_at TEXT,
    state TEXT NOT NULL CHECK (
        state IN ('active', 'superseded', 'retracted', 'expired')
    ),
    supersedes_id TEXT REFERENCES semantic_assertion(assertion_id) ON DELETE SET NULL,
    verification_state TEXT NOT NULL CHECK (
        verification_state IN ('unverified', 'verified')
    ),
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    freshness_class TEXT NOT NULL CHECK (
        freshness_class IN ('stable', 'changeable', 'time_sensitive')
    ),
    sensitivity TEXT NOT NULL CHECK (
        sensitivity IN ('standard', 'private', 'local_only', 'secret_prohibited')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CHECK (system_to IS NULL OR system_to >= system_from)
);

CREATE INDEX idx_semantic_assertion_lookup
ON semantic_assertion(subject_scope, subject, predicate, state, system_to, valid_to);

CREATE INDEX idx_semantic_assertion_source
ON semantic_assertion(source_id);

CREATE INDEX idx_semantic_assertion_supersedes
ON semantic_assertion(supersedes_id);

CREATE TABLE memory_operation (
    operation_id TEXT PRIMARY KEY,
    operation_type TEXT NOT NULL CHECK (
        operation_type IN (
            'create',
            'historical_change',
            'correct',
            'retract',
            'verify',
            'expire',
            'forget'
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

CREATE INDEX idx_memory_operation_target
ON memory_operation(target_kind, target_id, occurred_at);

CREATE VIEW current_semantic_assertion AS
SELECT
    assertion_rowid,
    assertion_id,
    subject_scope,
    subject,
    predicate,
    value_type,
    value_json,
    normalized_text,
    source_id,
    valid_from,
    valid_to,
    system_from,
    system_to,
    last_verified_at,
    state,
    supersedes_id,
    verification_state,
    confidence,
    freshness_class,
    sensitivity,
    created_at,
    updated_at
FROM semantic_assertion
WHERE state = 'active'
  AND system_to IS NULL
  AND valid_to IS NULL;

CREATE VIRTUAL TABLE semantic_assertion_fts USING fts5(
    normalized_text,
    content='semantic_assertion',
    content_rowid='assertion_rowid',
    tokenize='unicode61 remove_diacritics 2'
);

INSERT INTO semantic_assertion_fts(semantic_assertion_fts, rank)
VALUES('secure-delete', 1);

CREATE TRIGGER semantic_assertion_ai
AFTER INSERT ON semantic_assertion
BEGIN
    INSERT INTO semantic_assertion_fts(rowid, normalized_text)
    VALUES (new.assertion_rowid, new.normalized_text);
END;

CREATE TRIGGER semantic_assertion_ad
AFTER DELETE ON semantic_assertion
BEGIN
    INSERT INTO semantic_assertion_fts(
        semantic_assertion_fts,
        rowid,
        normalized_text
    ) VALUES (
        'delete',
        old.assertion_rowid,
        old.normalized_text
    );
END;

CREATE TRIGGER semantic_assertion_au
AFTER UPDATE OF normalized_text ON semantic_assertion
BEGIN
    INSERT INTO semantic_assertion_fts(
        semantic_assertion_fts,
        rowid,
        normalized_text
    ) VALUES (
        'delete',
        old.assertion_rowid,
        old.normalized_text
    );
    INSERT INTO semantic_assertion_fts(rowid, normalized_text)
    VALUES (new.assertion_rowid, new.normalized_text);
END;
