CREATE TABLE IF NOT EXISTS jarvis_engineering_schema_migration (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    name TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS engineering_incident (
    incident_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    symptom TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at_epoch REAL NOT NULL,
    updated_at_epoch REAL NOT NULL,
    affected_components_json TEXT NOT NULL,
    root_cause TEXT,
    accepted_fix TEXT,
    regression_tests_json TEXT NOT NULL,
    commit_sha TEXT,
    pr_number INTEGER,
    deployment_result TEXT,
    rollback_status TEXT,
    lessons_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS engineering_incident_evidence (
    evidence_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    reference TEXT NOT NULL,
    summary TEXT NOT NULL,
    occurred_at_epoch REAL NOT NULL,
    component_id TEXT,
    FOREIGN KEY(incident_id)
        REFERENCES engineering_incident(incident_id)
);

CREATE INDEX IF NOT EXISTS idx_incident_status_updated
ON engineering_incident(status, updated_at_epoch);

CREATE TABLE IF NOT EXISTS engineering_repair_attempt (
    attempt_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    trigger_id TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version INTEGER NOT NULL,
    action_id TEXT NOT NULL,
    action_kind TEXT NOT NULL,
    risk_class INTEGER NOT NULL,
    component_id TEXT NOT NULL,
    action_created_at_epoch REAL NOT NULL,
    attempt_number INTEGER NOT NULL,
    started_at_epoch REAL NOT NULL,
    pre_repair_evidence_json TEXT NOT NULL,
    finished_at_epoch REAL,
    execution_result TEXT,
    post_repair_evidence_json TEXT NOT NULL,
    verifier_result TEXT,
    next_retry_eligible_epoch REAL,
    verdict TEXT,
    FOREIGN KEY(incident_id)
        REFERENCES engineering_incident(incident_id)
);

CREATE INDEX IF NOT EXISTS idx_repair_attempt_incident
ON engineering_repair_attempt(
    incident_id, attempt_number, started_at_epoch
);

CREATE INDEX IF NOT EXISTS idx_repair_attempt_component_action_started
ON engineering_repair_attempt(
    component_id, action_kind, started_at_epoch
);
