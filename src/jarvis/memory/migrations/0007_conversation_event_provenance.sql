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
