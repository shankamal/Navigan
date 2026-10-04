ALTER TABLE environment_management.environments
  ADD COLUMN approved_status varchar(20),
  ADD COLUMN pending_approved_version bigint,
  ADD CONSTRAINT environments_approved_status_check
    CHECK (approved_status IS NULL OR approved_status IN ('ACTIVE','SUSPENDED','DEACTIVATED')),
  ADD CONSTRAINT environments_pending_approved_version_check
    CHECK (pending_approved_version IS NULL OR pending_approved_version > 0);

UPDATE environment_management.environments
SET pending_approved_version = approved_version,
    approved_version = NULL
WHERE status = 'APPROVED';

UPDATE environment_management.environments
SET approved_status = status
WHERE status IN ('ACTIVE','SUSPENDED','DEACTIVATED');
