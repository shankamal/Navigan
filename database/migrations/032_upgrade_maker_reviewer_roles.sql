BEGIN;
-- Upgrade planning is separate from Terraform cluster.plan permission.
INSERT INTO access_management.privileges(privilege_id,privilege_code,module_code,name,risk_level,scope_types,description)
VALUES ('PRV-UPGRADE-PLAN','cluster.upgrade.plan','CLUSTER','Create and revise upgrade plans','MEDIUM',ARRAY['CUSTOMER','PLATFORM','RESOURCE'],'Create, submit, cancel and reschedule upgrade requests within existing customer scope. Does not permit cluster provisioning or approval.')
ON CONFLICT(privilege_code) DO NOTHING;
INSERT INTO access_management.role_privileges(role_id,privilege_id,effect,created_by)
SELECT r.role_id,p.privilege_id,'ALLOW','SYSTEM'
FROM access_management.roles r CROSS JOIN access_management.privileges p
WHERE r.role_code='CLOUD_ENGINEER' AND r.role_type='SYSTEM_TEMPLATE'
AND p.privilege_code='cluster.upgrade.plan'
ON CONFLICT DO NOTHING;
-- Remove only the system grant introduced by 031; preserve explicit denies/custom grants.
DELETE FROM access_management.role_privileges rp
USING access_management.roles r,access_management.privileges p
WHERE rp.role_id=r.role_id AND rp.privilege_id=p.privilege_id
AND r.role_code='CLOUD_ENGINEER' AND r.role_type='SYSTEM_TEMPLATE'
AND p.privilege_code='cluster.upgrade.approve' AND rp.effect='ALLOW' AND rp.created_by='SYSTEM';
UPDATE access_management.users u SET authorization_revision=authorization_revision+1
WHERE EXISTS (SELECT 1 FROM access_management.user_role_assignments a JOIN access_management.roles r ON r.role_id=a.role_id
WHERE a.user_id=u.user_id AND a.status='ACTIVE' AND r.role_code IN ('CLOUD_ENGINEER','PLATFORM_ARCHITECT') AND r.role_type='SYSTEM_TEMPLATE');
COMMIT;
