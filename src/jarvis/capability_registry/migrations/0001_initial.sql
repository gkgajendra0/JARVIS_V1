CREATE TABLE IF NOT EXISTS jarvis_capability_schema_migration (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE capability_packages (
    package_id TEXT NOT NULL,
    package_version TEXT NOT NULL,
    package_digest TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    manifest_version INTEGER NOT NULL CHECK(manifest_version > 0),
    manifest_digest TEXT NOT NULL,
    admitted_release_sha TEXT NOT NULL,
    disposition TEXT NOT NULL
        CHECK(disposition IN ('available', 'retired', 'quarantined')),
    package_json TEXT NOT NULL,
    admitted_at TEXT NOT NULL,
    evidence_digest TEXT NOT NULL,
    PRIMARY KEY(package_id, package_version)
);

CREATE INDEX idx_capability_packages_capability
    ON capability_packages(capability_id, package_id, package_version);

CREATE TABLE capability_registry (
    capability_id TEXT PRIMARY KEY,
    selected_package_id TEXT,
    selected_package_version TEXT,
    selected_package_digest TEXT,
    desired_state TEXT NOT NULL
        CHECK(desired_state IN ('enabled', 'disabled')),
    generation INTEGER NOT NULL CHECK(generation > 0),
    updated_at TEXT NOT NULL,
    CHECK(
        (
            selected_package_id IS NULL
            AND selected_package_version IS NULL
            AND selected_package_digest IS NULL
        )
        OR
        (
            selected_package_id IS NOT NULL
            AND selected_package_version IS NOT NULL
            AND selected_package_digest IS NOT NULL
        )
    ),
    FOREIGN KEY(selected_package_id, selected_package_version)
        REFERENCES capability_packages(package_id, package_version)
);

CREATE TABLE capability_lifecycle_events (
    event_id TEXT PRIMARY KEY,
    capability_id TEXT NOT NULL,
    package_id TEXT,
    package_version TEXT,
    package_digest TEXT,
    event_kind TEXT NOT NULL,
    previous_generation INTEGER NOT NULL CHECK(previous_generation >= 0),
    new_generation INTEGER NOT NULL CHECK(new_generation > 0),
    reason_code TEXT NOT NULL,
    authority_ref TEXT,
    evidence_ref TEXT,
    occurred_at TEXT NOT NULL,
    event_digest TEXT NOT NULL UNIQUE
);

CREATE INDEX idx_capability_lifecycle_events_capability
    ON capability_lifecycle_events(capability_id, occurred_at, event_id);
