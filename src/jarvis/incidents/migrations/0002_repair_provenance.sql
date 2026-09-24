ALTER TABLE engineering_repair_attempt
ADD COLUMN trigger_snapshot_json TEXT;

ALTER TABLE engineering_repair_attempt
ADD COLUMN policy_snapshot_json TEXT;

ALTER TABLE engineering_repair_attempt
ADD COLUMN policy_digest TEXT
CHECK (policy_digest IS NULL OR length(policy_digest) = 64);

ALTER TABLE engineering_repair_attempt
ADD COLUMN verification_json TEXT;

CREATE INDEX IF NOT EXISTS idx_repair_attempt_policy_digest
ON engineering_repair_attempt(policy_digest);
