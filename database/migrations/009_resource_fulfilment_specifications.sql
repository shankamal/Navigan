BEGIN;

ALTER TABLE environment_management.bootstrap_remediation_requests
  ADD COLUMN IF NOT EXISTS desired_resources jsonb NOT NULL DEFAULT '{}'
  CHECK(jsonb_typeof(desired_resources)='object');

ALTER TABLE environment_management.bootstrap_remediation_requests
  ADD COLUMN IF NOT EXISTS verification_details jsonb NOT NULL DEFAULT '{}'
  CHECK(jsonb_typeof(verification_details)='object'),
  ADD COLUMN IF NOT EXISTS verified_by varchar(100),
  ADD COLUMN IF NOT EXISTS verified_at timestamptz;

COMMIT;
