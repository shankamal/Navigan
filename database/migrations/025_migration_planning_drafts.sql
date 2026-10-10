BEGIN;

-- Additive: old application images continue using assessment-only records.
ALTER TABLE migration_management.migrations
  ADD COLUMN planning_draft jsonb NOT NULL DEFAULT '{}'
  CHECK (jsonb_typeof(planning_draft) = 'object');

COMMIT;
