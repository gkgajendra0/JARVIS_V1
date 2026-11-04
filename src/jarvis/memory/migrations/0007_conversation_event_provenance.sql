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

-- Upgrade safety for projects forgotten before provenance tracking existed.
-- Nothing is deleted here. Jarvis replies and tool results in live projects,
-- saved at or after a forgotten project's first event, may restate it and have
-- no evidence edges to prove otherwise. They are quarantined: kept unchanged
-- in the encrypted database, but excluded from every context, search, source
-- read and evidence check until the owner reviews them and approves either
-- deletion or restoration (Windows Hello). Owner turns and omission markers
-- are never quarantined; nothing is quarantined if no project was forgotten.
CREATE TABLE conversation_event_quarantine (
    event_id TEXT PRIMARY KEY REFERENCES conversation_event(event_id),
    reason TEXT NOT NULL CHECK (reason IN ('untracked_after_forgotten_project'))
) WITHOUT ROWID;

INSERT INTO conversation_event_quarantine(event_id, reason)
SELECT e.event_id, 'untracked_after_forgotten_project'
FROM conversation_event e
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
);
