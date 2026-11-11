BEGIN;
ALTER TABLE cluster_management.upgrade_plans ADD COLUMN plan_spec jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE cluster_management.upgrade_plans DROP CONSTRAINT upgrade_plan_version_change;
ALTER TABLE cluster_management.upgrade_plans ADD CONSTRAINT upgrade_plan_version_change CHECK (
 current_version <> target_version OR COALESCE(plan_spec->>'scope','CLUSTER') IN ('NODES','ADDONS')
);
INSERT INTO access_management.privileges(privilege_id,privilege_code,module_code,name,risk_level,scope_types,description)
VALUES ('PRV-UPGRADE-EXECUTE','cluster.upgrade.execute','CLUSTER','Execute approved upgrades','HIGH',ARRAY['CUSTOMER','PLATFORM','RESOURCE'],'Start approved component upgrades within their reviewed maintenance windows and advance already-started operations. Does not grant Terraform apply or approval.')
ON CONFLICT(privilege_code) DO NOTHING;
INSERT INTO access_management.role_privileges(role_id,privilege_id,effect,created_by)
SELECT r.role_id,p.privilege_id,'ALLOW','SYSTEM' FROM access_management.roles r CROSS JOIN access_management.privileges p
WHERE r.role_code='CLOUD_ENGINEER' AND r.role_type='SYSTEM_TEMPLATE' AND p.privilege_code='cluster.upgrade.execute'
ON CONFLICT DO NOTHING;
UPDATE access_management.users u SET authorization_revision=authorization_revision+1
WHERE EXISTS (SELECT 1 FROM access_management.user_role_assignments a JOIN access_management.roles r ON r.role_id=a.role_id
WHERE a.user_id=u.user_id AND a.status='ACTIVE' AND r.role_code='CLOUD_ENGINEER' AND r.role_type='SYSTEM_TEMPLATE');
COMMIT;
