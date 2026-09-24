CREATE TABLE engineering_knowledge_search_document (
    revision_id TEXT PRIMARY KEY,
    searchable_text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (
        length(content_sha256) = 64
        AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    updated_at_epoch REAL NOT NULL,
    FOREIGN KEY(revision_id)
        REFERENCES engineering_knowledge_revision(revision_id)
        ON DELETE CASCADE,
    CHECK (length(trim(searchable_text)) > 0)
);

CREATE VIRTUAL TABLE engineering_knowledge_fts USING fts5(
    revision_id UNINDEXED,
    searchable_text,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE engineering_knowledge_embedding (
    revision_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    dtype TEXT NOT NULL CHECK (dtype = 'float32'),
    byte_order TEXT NOT NULL CHECK (byte_order = 'little'),
    normalized INTEGER NOT NULL CHECK (normalized IN (0, 1)),
    content_sha256 TEXT NOT NULL CHECK (
        length(content_sha256) = 64
        AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    embedding_blob BLOB NOT NULL,
    created_at_epoch REAL NOT NULL,
    updated_at_epoch REAL NOT NULL,
    FOREIGN KEY(revision_id)
        REFERENCES engineering_knowledge_revision(revision_id)
        ON DELETE CASCADE,
    CHECK (length(trim(model_id)) > 0),
    CHECK (length(trim(model_revision)) > 0),
    CHECK (length(embedding_blob) = dimension * 4)
);

CREATE INDEX idx_engineering_knowledge_embedding_contract
ON engineering_knowledge_embedding(
    model_id,
    model_revision,
    dimension,
    dtype,
    byte_order,
    normalized,
    content_sha256
);
