CREATE TABLE engineering_knowledge_identity (
    knowledge_id TEXT PRIMARY KEY,
    stable_label TEXT,
    created_at_epoch REAL NOT NULL,
    created_by TEXT NOT NULL,
    CHECK (length(trim(knowledge_id)) > 0),
    CHECK (stable_label IS NULL OR length(trim(stable_label)) > 0),
    CHECK (length(trim(created_by)) > 0)
);

CREATE TABLE engineering_knowledge_revision (
    revision_id TEXT PRIMARY KEY,
    knowledge_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    parent_revision_id TEXT,
    supersedes_revision_id TEXT,
    kind_namespace TEXT NOT NULL,
    normalized_summary TEXT NOT NULL,
    valid_from_epoch REAL,
    valid_to_epoch REAL,
    system_from_epoch REAL NOT NULL,
    system_to_epoch REAL,
    sensitivity TEXT NOT NULL CHECK (
        sensitivity IN ('standard', 'private', 'local_only')
    ),
    freshness_state TEXT NOT NULL CHECK (
        freshness_state IN ('current', 'revalidation_required', 'expired')
    ),
    canonicalization TEXT NOT NULL CHECK (
        canonicalization = 'rfc8785'
    ),
    digest_algorithm TEXT NOT NULL CHECK (
        digest_algorithm = 'sha256'
    ),
    canonical_digest TEXT NOT NULL CHECK (
        length(canonical_digest) = 64
        AND canonical_digest NOT GLOB '*[^0-9a-f]*'
    ),
    created_at_epoch REAL NOT NULL,
    created_by TEXT NOT NULL,
    FOREIGN KEY(knowledge_id)
        REFERENCES engineering_knowledge_identity(knowledge_id)
        ON DELETE RESTRICT,
    FOREIGN KEY(parent_revision_id)
        REFERENCES engineering_knowledge_revision(revision_id)
        ON DELETE RESTRICT,
    FOREIGN KEY(supersedes_revision_id)
        REFERENCES engineering_knowledge_revision(revision_id)
        ON DELETE RESTRICT,
    UNIQUE(knowledge_id, revision_number),
    CHECK (length(trim(revision_id)) > 0),
    CHECK (length(trim(kind_namespace)) > 0),
    CHECK (length(trim(normalized_summary)) > 0),
    CHECK (length(trim(created_by)) > 0),
    CHECK (
        valid_to_epoch IS NULL
        OR valid_from_epoch IS NULL
        OR valid_to_epoch >= valid_from_epoch
    ),
    CHECK (
        system_to_epoch IS NULL
        OR system_to_epoch >= system_from_epoch
    ),
    CHECK (
        parent_revision_id IS NULL
        OR parent_revision_id <> revision_id
    ),
    CHECK (
        supersedes_revision_id IS NULL
        OR supersedes_revision_id <> revision_id
    )
);

CREATE INDEX idx_engineering_knowledge_revision_identity
ON engineering_knowledge_revision(knowledge_id, revision_number);

CREATE INDEX idx_engineering_knowledge_revision_kind
ON engineering_knowledge_revision(kind_namespace, system_to_epoch, valid_to_epoch);

CREATE TABLE engineering_knowledge_facet (
    facet_id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL,
    facet_type TEXT NOT NULL,
    schema_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    schema_digest TEXT NOT NULL CHECK (
        length(schema_digest) = 64
        AND schema_digest NOT GLOB '*[^0-9a-f]*'
    ),
    producer TEXT NOT NULL,
    payload_json TEXT,
    protected_payload_ref TEXT,
    payload_digest TEXT NOT NULL CHECK (
        length(payload_digest) = 64
        AND payload_digest NOT GLOB '*[^0-9a-f]*'
    ),
    created_at_epoch REAL NOT NULL,
    FOREIGN KEY(revision_id)
        REFERENCES engineering_knowledge_revision(revision_id)
        ON DELETE RESTRICT,
    UNIQUE(revision_id, facet_type, schema_id, schema_version),
    CHECK (length(trim(facet_id)) > 0),
    CHECK (length(trim(facet_type)) > 0),
    CHECK (length(trim(schema_id)) > 0),
    CHECK (length(trim(schema_version)) > 0),
    CHECK (length(trim(producer)) > 0),
    CHECK (
        (payload_json IS NOT NULL AND protected_payload_ref IS NULL)
        OR
        (payload_json IS NULL AND protected_payload_ref IS NOT NULL)
    )
);

CREATE INDEX idx_engineering_knowledge_facet_revision
ON engineering_knowledge_facet(revision_id, facet_type);

CREATE TABLE engineering_knowledge_applicability (
    applicability_id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL,
    target_namespace TEXT NOT NULL,
    target_identity TEXT NOT NULL,
    matcher_type TEXT NOT NULL,
    constraint_json TEXT NOT NULL,
    required INTEGER NOT NULL CHECK (required IN (0, 1)),
    created_at_epoch REAL NOT NULL,
    FOREIGN KEY(revision_id)
        REFERENCES engineering_knowledge_revision(revision_id)
        ON DELETE RESTRICT,
    CHECK (length(trim(applicability_id)) > 0),
    CHECK (length(trim(target_namespace)) > 0),
    CHECK (length(trim(target_identity)) > 0),
    CHECK (length(trim(matcher_type)) > 0)
);

CREATE INDEX idx_engineering_knowledge_applicability_revision
ON engineering_knowledge_applicability(
    revision_id, target_namespace, target_identity
);

CREATE TABLE engineering_evidence (
    evidence_id TEXT PRIMARY KEY,
    evidence_type TEXT NOT NULL,
    source_class TEXT NOT NULL,
    canonical_reference TEXT NOT NULL,
    summary TEXT NOT NULL,
    occurred_at_epoch REAL,
    observed_at_epoch REAL NOT NULL,
    sensitivity TEXT NOT NULL CHECK (
        sensitivity IN ('standard', 'private', 'local_only')
    ),
    producer TEXT NOT NULL,
    integrity_algorithm TEXT,
    integrity_digest TEXT,
    created_at_epoch REAL NOT NULL,
    CHECK (length(trim(evidence_id)) > 0),
    CHECK (length(trim(evidence_type)) > 0),
    CHECK (length(trim(source_class)) > 0),
    CHECK (length(trim(canonical_reference)) > 0),
    CHECK (length(trim(summary)) > 0),
    CHECK (length(trim(producer)) > 0),
    CHECK (
        (integrity_algorithm IS NULL AND integrity_digest IS NULL)
        OR
        (
            integrity_algorithm = 'sha256'
            AND integrity_digest IS NOT NULL
            AND length(integrity_digest) = 64
            AND integrity_digest NOT GLOB '*[^0-9a-f]*'
        )
    )
);

CREATE INDEX idx_engineering_evidence_reference
ON engineering_evidence(source_class, canonical_reference);

CREATE TABLE engineering_knowledge_evidence_link (
    revision_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    created_at_epoch REAL NOT NULL,
    PRIMARY KEY(revision_id, evidence_id, relation_type),
    FOREIGN KEY(revision_id)
        REFERENCES engineering_knowledge_revision(revision_id)
        ON DELETE RESTRICT,
    FOREIGN KEY(evidence_id)
        REFERENCES engineering_evidence(evidence_id)
        ON DELETE RESTRICT,
    CHECK (length(trim(relation_type)) > 0)
);

CREATE INDEX idx_engineering_knowledge_evidence_link_evidence
ON engineering_knowledge_evidence_link(evidence_id, relation_type);

CREATE TABLE engineering_knowledge_lifecycle_event (
    event_id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL,
    from_state TEXT CHECK (
        from_state IS NULL
        OR from_state IN (
            'candidate', 'staged', 'accepted',
            'rejected', 'retired', 'superseded'
        )
    ),
    to_state TEXT NOT NULL CHECK (
        to_state IN (
            'candidate', 'staged', 'accepted',
            'rejected', 'retired', 'superseded'
        )
    ),
    reason_code TEXT NOT NULL,
    actor TEXT NOT NULL,
    policy_id TEXT,
    evidence_ids_json TEXT NOT NULL,
    occurred_at_epoch REAL NOT NULL,
    FOREIGN KEY(revision_id)
        REFERENCES engineering_knowledge_revision(revision_id)
        ON DELETE RESTRICT,
    CHECK (length(trim(event_id)) > 0),
    CHECK (length(trim(reason_code)) > 0),
    CHECK (length(trim(actor)) > 0),
    CHECK (from_state IS NULL OR from_state <> to_state)
);

CREATE INDEX idx_engineering_knowledge_lifecycle_revision
ON engineering_knowledge_lifecycle_event(
    revision_id, occurred_at_epoch, event_id
);

CREATE TABLE engineering_attestation (
    attestation_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    subject_digest TEXT NOT NULL CHECK (
        length(subject_digest) = 64
        AND subject_digest NOT GLOB '*[^0-9a-f]*'
    ),
    predicate_type TEXT NOT NULL,
    producer TEXT NOT NULL,
    expected_contract_json TEXT NOT NULL,
    observed_result_json TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (
        verdict IN ('pass', 'fail', 'inconclusive')
    ),
    evidence_ids_json TEXT NOT NULL,
    observed_at_epoch REAL NOT NULL,
    created_at_epoch REAL NOT NULL,
    CHECK (length(trim(attestation_id)) > 0),
    CHECK (length(trim(subject_type)) > 0),
    CHECK (length(trim(subject_id)) > 0),
    CHECK (length(trim(predicate_type)) > 0),
    CHECK (length(trim(producer)) > 0)
);

CREATE INDEX idx_engineering_attestation_subject
ON engineering_attestation(subject_type, subject_id, predicate_type);

CREATE VIEW engineering_knowledge_revision_state AS
SELECT
    revision.revision_id,
    revision.knowledge_id,
    COALESCE(
        (
            SELECT lifecycle.to_state
            FROM engineering_knowledge_lifecycle_event AS lifecycle
            WHERE lifecycle.revision_id = revision.revision_id
            ORDER BY lifecycle.occurred_at_epoch DESC, lifecycle.event_id DESC
            LIMIT 1
        ),
        'candidate'
    ) AS lifecycle_state
FROM engineering_knowledge_revision AS revision;

CREATE TRIGGER engineering_knowledge_identity_no_update
BEFORE UPDATE ON engineering_knowledge_identity
BEGIN
    SELECT RAISE(ABORT, 'engineering knowledge identities are immutable');
END;

CREATE TRIGGER engineering_knowledge_identity_no_delete
BEFORE DELETE ON engineering_knowledge_identity
BEGIN
    SELECT RAISE(ABORT, 'engineering knowledge identities are immutable');
END;

CREATE TRIGGER engineering_knowledge_revision_no_update
BEFORE UPDATE ON engineering_knowledge_revision
BEGIN
    SELECT RAISE(ABORT, 'engineering knowledge revisions are immutable');
END;

CREATE TRIGGER engineering_knowledge_revision_no_delete
BEFORE DELETE ON engineering_knowledge_revision
BEGIN
    SELECT RAISE(ABORT, 'engineering knowledge revisions are immutable');
END;

CREATE TRIGGER engineering_knowledge_facet_no_update
BEFORE UPDATE ON engineering_knowledge_facet
BEGIN
    SELECT RAISE(ABORT, 'engineering knowledge facets are immutable');
END;

CREATE TRIGGER engineering_knowledge_facet_no_delete
BEFORE DELETE ON engineering_knowledge_facet
BEGIN
    SELECT RAISE(ABORT, 'engineering knowledge facets are immutable');
END;

CREATE TRIGGER engineering_knowledge_applicability_no_update
BEFORE UPDATE ON engineering_knowledge_applicability
BEGIN
    SELECT RAISE(ABORT, 'engineering knowledge applicability is immutable');
END;

CREATE TRIGGER engineering_knowledge_applicability_no_delete
BEFORE DELETE ON engineering_knowledge_applicability
BEGIN
    SELECT RAISE(ABORT, 'engineering knowledge applicability is immutable');
END;

CREATE TRIGGER engineering_evidence_no_update
BEFORE UPDATE ON engineering_evidence
BEGIN
    SELECT RAISE(ABORT, 'engineering evidence is immutable');
END;

CREATE TRIGGER engineering_evidence_no_delete
BEFORE DELETE ON engineering_evidence
BEGIN
    SELECT RAISE(ABORT, 'engineering evidence is immutable');
END;

CREATE TRIGGER engineering_knowledge_evidence_link_no_update
BEFORE UPDATE ON engineering_knowledge_evidence_link
BEGIN
    SELECT RAISE(ABORT, 'engineering knowledge evidence links are immutable');
END;

CREATE TRIGGER engineering_knowledge_evidence_link_no_delete
BEFORE DELETE ON engineering_knowledge_evidence_link
BEGIN
    SELECT RAISE(ABORT, 'engineering knowledge evidence links are immutable');
END;

CREATE TRIGGER engineering_knowledge_lifecycle_event_no_update
BEFORE UPDATE ON engineering_knowledge_lifecycle_event
BEGIN
    SELECT RAISE(ABORT, 'engineering knowledge lifecycle events are immutable');
END;

CREATE TRIGGER engineering_knowledge_lifecycle_event_no_delete
BEFORE DELETE ON engineering_knowledge_lifecycle_event
BEGIN
    SELECT RAISE(ABORT, 'engineering knowledge lifecycle events are immutable');
END;

CREATE TRIGGER engineering_attestation_no_update
BEFORE UPDATE ON engineering_attestation
BEGIN
    SELECT RAISE(ABORT, 'engineering attestations are immutable');
END;

CREATE TRIGGER engineering_attestation_no_delete
BEFORE DELETE ON engineering_attestation
BEGIN
    SELECT RAISE(ABORT, 'engineering attestations are immutable');
END;
