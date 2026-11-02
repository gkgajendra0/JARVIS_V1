-- Evidence provenance for saved Jarvis replies and tool results.
-- Each non-user event records which archived events were in the context it
-- was generated from. Forgetting a project follows these edges and removes
-- every reply derived from it, in any project. Owner-authored user turns are
-- never derived and carry no edges.
ALTER TABLE conversation_event
ADD COLUMN provenance_tracked INTEGER NOT NULL DEFAULT 0
CHECK (provenance_tracked IN (0, 1));

CREATE TABLE conversation_event_dependency (
    event_id TEXT NOT NULL REFERENCES conversation_event(event_id),
    source_event_id TEXT NOT NULL REFERENCES conversation_event(event_id),
    PRIMARY KEY (event_id, source_event_id),
    CHECK (event_id <> source_event_id)
) WITHOUT ROWID;

CREATE INDEX conversation_event_dependency_source
ON conversation_event_dependency(source_event_id);

-- Owner-visible record of what the one-time repair below removed.
CREATE TABLE conversation_repair_log (
    repair_id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    affected_events INTEGER NOT NULL CHECK (affected_events >= 0)
);

-- One-time repair for projects forgotten before provenance tracking existed.
-- Applies the consequence of a forget the owner already approved: Jarvis
-- replies and tool results in live projects, saved at or after the forgotten
-- project's first event, may restate it and have no evidence edges to prove
-- otherwise, so they become tombstones too. Owner turns and omission markers
-- are kept; nothing is removed when no project has been forgotten.
UPDATE conversation_thread
SET archive_revision = archive_revision + 1
WHERE thread_id IN (
    SELECT DISTINCT e.thread_id FROM conversation_event e
    JOIN conversation_thread t ON t.thread_id = e.thread_id
    JOIN conversation_workspace w ON w.project_id = t.project_id
    WHERE w.forgotten_at IS NULL AND e.role <> 'user'
    AND e.payload_sha256 <> '0000000000000000000000000000000000000000000000000000000000000000'
    AND instr(e.text, '"capture":"omitted"') = 0
    AND EXISTS (
        SELECT 1 FROM conversation_workspace f
        JOIN conversation_thread ft ON ft.project_id = f.project_id
        JOIN conversation_event fe ON fe.thread_id = ft.thread_id
        WHERE f.forgotten_at IS NOT NULL AND fe.accepted_at <= e.accepted_at
    )
);

UPDATE conversation_event
SET text = '[forgotten]', role = 'tool', delivery = 'failed',
    payload_sha256 = '0000000000000000000000000000000000000000000000000000000000000000'
WHERE role <> 'user'
AND payload_sha256 <> '0000000000000000000000000000000000000000000000000000000000000000'
AND instr(text, '"capture":"omitted"') = 0
AND thread_id IN (
    SELECT t.thread_id FROM conversation_thread t
    JOIN conversation_workspace w ON w.project_id = t.project_id
    WHERE w.forgotten_at IS NULL
)
AND EXISTS (
    SELECT 1 FROM conversation_workspace f
    JOIN conversation_thread ft ON ft.project_id = f.project_id
    JOIN conversation_event fe ON fe.thread_id = ft.thread_id
    WHERE f.forgotten_at IS NOT NULL AND fe.accepted_at <= conversation_event.accepted_at
);

-- changes() counts only the UPDATE above, not the search-index triggers.
INSERT INTO conversation_repair_log(kind, affected_events)
VALUES ('forgotten_project_derived_replies', changes());

INSERT INTO conversation_event_fts(conversation_event_fts) VALUES ('optimize');
