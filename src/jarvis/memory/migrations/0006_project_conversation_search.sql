-- Rebuildable full-text index over original project conversation events.
-- conversation_event remains the canonical source; this index is derived data.
-- secure-delete removes forgotten tokens from the index b-tree immediately
-- instead of leaving them until a later segment merge.
CREATE VIRTUAL TABLE conversation_event_fts USING fts5(
    text,
    content='conversation_event',
    content_rowid='rowid',
    tokenize='porter unicode61 remove_diacritics 2'
);

INSERT INTO conversation_event_fts(conversation_event_fts, rank)
VALUES ('secure-delete', 1);

INSERT INTO conversation_event_fts(rowid, text)
SELECT rowid, text FROM conversation_event;

CREATE TRIGGER conversation_event_fts_insert
AFTER INSERT ON conversation_event
BEGIN
    INSERT INTO conversation_event_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TRIGGER conversation_event_fts_delete
AFTER DELETE ON conversation_event
BEGIN
    INSERT INTO conversation_event_fts(conversation_event_fts, rowid, text)
    VALUES ('delete', old.rowid, old.text);
END;

CREATE TRIGGER conversation_event_fts_update
AFTER UPDATE OF text ON conversation_event
BEGIN
    INSERT INTO conversation_event_fts(conversation_event_fts, rowid, text)
    VALUES ('delete', old.rowid, old.text);
    INSERT INTO conversation_event_fts(rowid, text) VALUES (new.rowid, new.text);
END;
