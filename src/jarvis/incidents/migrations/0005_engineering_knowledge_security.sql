CREATE TRIGGER engineering_knowledge_facet_freeze_after_candidate
BEFORE INSERT ON engineering_knowledge_facet
WHEN EXISTS (
    SELECT 1
    FROM engineering_knowledge_lifecycle_event
    WHERE revision_id = NEW.revision_id
)
BEGIN
    SELECT RAISE(
        ABORT,
        'engineering knowledge facets are frozen after candidate creation'
    );
END;

CREATE TRIGGER engineering_knowledge_applicability_freeze_after_candidate
BEFORE INSERT ON engineering_knowledge_applicability
WHEN EXISTS (
    SELECT 1
    FROM engineering_knowledge_lifecycle_event
    WHERE revision_id = NEW.revision_id
)
BEGIN
    SELECT RAISE(
        ABORT,
        'engineering knowledge applicability is frozen after candidate creation'
    );
END;

CREATE TRIGGER engineering_knowledge_evidence_link_freeze_after_terminal
BEFORE INSERT ON engineering_knowledge_evidence_link
WHEN EXISTS (
    SELECT 1
    FROM engineering_knowledge_revision_state
    WHERE revision_id = NEW.revision_id
      AND lifecycle_state IN (
          'accepted', 'rejected', 'retired', 'superseded'
      )
)
BEGIN
    SELECT RAISE(
        ABORT,
        'engineering knowledge evidence links are frozen after terminal promotion'
    );
END;

CREATE TRIGGER engineering_attestation_freeze_after_terminal
BEFORE INSERT ON engineering_attestation
WHEN NEW.subject_type = 'knowledge_revision'
AND EXISTS (
    SELECT 1
    FROM engineering_knowledge_revision_state
    WHERE revision_id = NEW.subject_id
      AND lifecycle_state IN (
          'accepted', 'rejected', 'retired', 'superseded'
      )
)
BEGIN
    SELECT RAISE(
        ABORT,
        'engineering knowledge attestations are frozen after terminal promotion'
    );
END;
