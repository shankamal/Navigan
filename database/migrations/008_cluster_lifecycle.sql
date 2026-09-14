BEGIN;

ALTER TABLE cluster_management.clusters
  DROP CONSTRAINT IF EXISTS clusters_status_check;

ALTER TABLE cluster_management.clusters
  ADD CONSTRAINT clusters_status_check CHECK(status IN (
    'DRAFT','SUBMITTED','UNDER_REVIEW','APPROVED','PLAN_RUNNING','PLAN_READY',
    'APPLYING','ACTIVE','STOPPING','STOPPED','STARTING','DELETING','DELETED',
    'FAILED','REJECTED','CANCELLED'
  ));

INSERT INTO access_management.role_privileges(
  role_id,
  privilege_id,
  effect,
  created_by
)
SELECT role.role_id, privilege.privilege_id, 'ALLOW', 'SYSTEM'
FROM access_management.roles role
JOIN access_management.privileges privilege
  ON privilege.privilege_code IN ('cluster.apply', 'cluster.decommission')
WHERE role.role_code IN ('PLATFORM_ARCHITECT', 'PLATFORM_ADMINISTRATOR')
ON CONFLICT DO NOTHING;

COMMIT;
