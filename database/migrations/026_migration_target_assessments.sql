-- Target assessment evidence is tenant-scoped through its migration parent.
-- Control-plane discovery does not authorize deployment or mark compatibility ready.
CREATE TABLE IF NOT EXISTS migration_management.migration_target_assessments (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  migration_id VARCHAR(40) NOT NULL REFERENCES migration_management.migrations(migration_id),
  target_cluster_id VARCHAR(128) NOT NULL,
  assessment_version INTEGER NOT NULL,
  target_snapshot JSONB NOT NULL,
  evidence_level VARCHAR(40) NOT NULL,
  created_by VARCHAR(128) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS migration_target_assessments_latest_idx
  ON migration_management.migration_target_assessments(migration_id, created_at DESC, id DESC);
