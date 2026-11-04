-- Canonical encrypted-memory connection only. No plaintext fallback.
CREATE TABLE conversation_topic_checkpoint (
    topic_key TEXT PRIMARY KEY,
    source_turn_id TEXT NOT NULL,
    source_at TEXT NOT NULL,
    state_json TEXT NOT NULL CHECK(length(state_json) BETWEEN 2 AND 8192)
);
CREATE TABLE conversation_topic_tombstone (
    topic_key TEXT PRIMARY KEY,
    forgotten_at TEXT NOT NULL,
    source_turn_id TEXT NOT NULL
);
