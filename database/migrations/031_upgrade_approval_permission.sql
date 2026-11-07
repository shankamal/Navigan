BEGIN;
INSERT INTO access_management.privileges(privilege_id,privilege_code,module_code,name,risk_level,scope_types,description)
VALUES ('PRV-UPGRADE-APPROVE','cluster.upgrade.approve','CLUSTER','Approve upgrade plans','HIGH',ARRAY['CUSTOMER','PLATFORM','RESOURCE'],'Review another user''s container or utility upgrade plan. Does not grant cluster creation approval.')
ON CONFLICT(privilege_code) DO NOTHING;
INSERT INTO access_management.role_privileges(role_id,privilege_id,effect,created_by)
SELECT r.role_id,p.privilege_id,'ALLOW','SYSTEM'
FROM access_management.roles r CROSS JOIN access_management.privileges p
WHERE r.role_code IN ('CLOUD_ENGINEER','PLATFORM_ARCHITECT') AND r.role_type='SYSTEM_TEMPLATE'
AND p.privilege_code='cluster.upgrade.approve'
ON CONFLICT DO NOTHING;
UPDATE access_management.users u SET authorization_revision=authorization_revision+1
WHERE EXISTS (SELECT 1 FROM access_management.user_role_assignments a JOIN access_management.roles r ON r.role_id=a.role_id
WHERE a.user_id=u.user_id AND a.status='ACTIVE' AND r.role_code IN ('CLOUD_ENGINEER','PLATFORM_ARCHITECT') AND r.role_type='SYSTEM_TEMPLATE');
COMMIT;
