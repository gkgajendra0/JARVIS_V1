CREATE TABLE semantic_assertion_embedding (
    assertion_id TEXT PRIMARY KEY
        REFERENCES semantic_assertion(assertion_id)
        ON DELETE CASCADE,
    model_id TEXT NOT NULL CHECK (length(model_id) > 0),
    model_revision TEXT NOT NULL CHECK (length(model_revision) > 0),
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    dtype TEXT NOT NULL CHECK (dtype = 'float32'),
    byte_order TEXT NOT NULL CHECK (byte_order = 'little'),
    normalized INTEGER NOT NULL CHECK (normalized IN (0, 1)),
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    embedding_blob BLOB NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (length(embedding_blob) = dimension * 4)
);

CREATE INDEX idx_semantic_assertion_embedding_contract
ON semantic_assertion_embedding(
    model_id,
    model_revision,
    dimension,
    dtype,
    byte_order,
    normalized,
    content_sha256
);
