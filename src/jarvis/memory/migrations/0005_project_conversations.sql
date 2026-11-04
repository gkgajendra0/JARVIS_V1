CREATE TABLE conversation_workspace (
    project_id TEXT PRIMARY KEY,
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 160),
    aliases_json TEXT NOT NULL DEFAULT '[]',
    epoch INTEGER NOT NULL DEFAULT 0 CHECK(epoch >= 0),
    retention_paused INTEGER NOT NULL DEFAULT 0 CHECK(retention_paused IN (0,1)),
    forgotten_at TEXT
);
CREATE TABLE conversation_thread (
    thread_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES conversation_workspace(project_id),
    archive_revision INTEGER NOT NULL DEFAULT 0 CHECK(archive_revision >= 0),
    last_sequence INTEGER NOT NULL DEFAULT 0 CHECK(last_sequence >= 0),
    state_json TEXT,
    covered_sequence INTEGER NOT NULL DEFAULT 0 CHECK(covered_sequence >= 0)
);
CREATE TABLE conversation_event (
    event_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES conversation_thread(thread_id),
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    revision INTEGER NOT NULL CHECK(revision > 0),
    segment_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user','assistant','tool')),
    text TEXT NOT NULL CHECK(length(text) BETWEEN 1 AND 65536),
    accepted_at TEXT NOT NULL,
    delivery TEXT NOT NULL CHECK(delivery IN ('complete','partial','failed')),
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64),
    UNIQUE(thread_id, sequence)
);
CREATE TABLE conversation_selection (
    owner_scope TEXT PRIMARY KEY CHECK(owner_scope = 'owner'),
    project_id TEXT NOT NULL REFERENCES conversation_workspace(project_id),
    thread_id TEXT NOT NULL REFERENCES conversation_thread(thread_id),
    revision INTEGER NOT NULL CHECK(revision >= 0)
);
CREATE INDEX conversation_thread_project ON conversation_thread(project_id);
CREATE INDEX conversation_event_request ON conversation_event(thread_id,request_id);
