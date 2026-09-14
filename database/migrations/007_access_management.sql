CREATE SCHEMA access_management;

CREATE TABLE access_management.users (
 user_id varchar(100) PRIMARY KEY,
 username varchar(255) NOT NULL,
 display_name varchar(255) NOT NULL,
 email varchar(320),
 status varchar(30) NOT NULL DEFAULT 'ACTIVE'
  CHECK(status IN ('INVITED','ACTIVE','DISABLED','DEACTIVATED')),
 authorization_revision bigint NOT NULL DEFAULT 1 CHECK(authorization_revision > 0),
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_by varchar(100),
 updated_at timestamptz
);
CREATE UNIQUE INDEX access_users_username_uq
 ON access_management.users(lower(btrim(username)));
CREATE UNIQUE INDEX access_users_email_uq
 ON access_management.users(lower(btrim(email))) WHERE email IS NOT NULL;

CREATE TABLE access_management.roles (
 role_id varchar(50) PRIMARY KEY,
 role_code varchar(100) NOT NULL UNIQUE,
 role_name varchar(255) NOT NULL,
 description text NOT NULL DEFAULT '',
 role_type varchar(30) NOT NULL CHECK(role_type IN ('SYSTEM_TEMPLATE','CUSTOM')),
 status varchar(30) NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','RETIRED')),
 version bigint NOT NULL DEFAULT 1 CHECK(version > 0),
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_by varchar(100),
 updated_at timestamptz
);

CREATE TABLE access_management.privileges (
 privilege_id varchar(50) PRIMARY KEY,
 privilege_code varchar(150) NOT NULL UNIQUE,
 module_code varchar(50) NOT NULL,
 name varchar(255) NOT NULL,
 description text NOT NULL,
 risk_level varchar(20) NOT NULL CHECK(risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')),
 scope_types text[] NOT NULL,
 active boolean NOT NULL DEFAULT true,
 CHECK(scope_types <@ ARRAY['SELF','CUSTOMER','PLATFORM','RESOURCE']::text[]),
 CHECK(cardinality(scope_types) > 0)
);

CREATE TABLE access_management.role_privileges (
 role_id varchar(50) NOT NULL REFERENCES access_management.roles,
 privilege_id varchar(50) NOT NULL REFERENCES access_management.privileges,
 effect varchar(10) NOT NULL CHECK(effect IN ('ALLOW','DENY')),
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(role_id,privilege_id)
);

CREATE TABLE access_management.user_role_assignments (
 assignment_id varchar(50) PRIMARY KEY,
 user_id varchar(100) NOT NULL REFERENCES access_management.users,
 role_id varchar(50) NOT NULL REFERENCES access_management.roles,
 valid_from timestamptz NOT NULL DEFAULT now(),
 valid_until timestamptz,
 status varchar(20) NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','REVOKED')),
 reason text NOT NULL,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 revoked_by varchar(100),
 revoked_at timestamptz,
 CHECK(valid_until IS NULL OR valid_until > valid_from),
 CHECK((status='ACTIVE' AND revoked_at IS NULL AND revoked_by IS NULL)
    OR (status='REVOKED' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL))
);
CREATE UNIQUE INDEX active_user_role_assignment_uq
 ON access_management.user_role_assignments(user_id,role_id)
 WHERE status='ACTIVE';

CREATE TABLE access_management.user_privilege_assignments (
 assignment_id varchar(50) PRIMARY KEY,
 user_id varchar(100) NOT NULL REFERENCES access_management.users,
 privilege_id varchar(50) NOT NULL REFERENCES access_management.privileges,
 effect varchar(10) NOT NULL CHECK(effect IN ('ALLOW','DENY')),
 valid_from timestamptz NOT NULL DEFAULT now(),
 valid_until timestamptz,
 status varchar(20) NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','REVOKED')),
 reason text NOT NULL,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 revoked_by varchar(100),
 revoked_at timestamptz,
 CHECK(valid_until IS NULL OR valid_until > valid_from),
 CHECK((status='ACTIVE' AND revoked_at IS NULL AND revoked_by IS NULL)
    OR (status='REVOKED' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL))
);
CREATE UNIQUE INDEX active_user_privilege_assignment_uq
 ON access_management.user_privilege_assignments(user_id,privilege_id,effect)
 WHERE status='ACTIVE';

CREATE TABLE access_management.access_scopes (
 scope_id varchar(50) PRIMARY KEY,
 scope_type varchar(20) NOT NULL CHECK(scope_type IN ('SELF','CUSTOMER','PLATFORM','RESOURCE')),
 customer_id varchar(50) REFERENCES customer_management.customers,
 resource_type varchar(30),
 resource_id varchar(50),
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK(
  (scope_type IN ('SELF','PLATFORM') AND customer_id IS NULL AND resource_type IS NULL AND resource_id IS NULL)
  OR (scope_type='CUSTOMER' AND customer_id IS NOT NULL AND resource_type IS NULL AND resource_id IS NULL)
  OR (scope_type='RESOURCE' AND customer_id IS NOT NULL
      AND resource_type IN ('ENVIRONMENT','CLUSTER') AND resource_id IS NOT NULL)
 )
);
CREATE UNIQUE INDEX access_scope_natural_uq ON access_management.access_scopes(
 scope_type,
 coalesce(customer_id,''),
 coalesce(resource_type,''),
 coalesce(resource_id,'')
);

CREATE TABLE access_management.user_role_scopes (
 assignment_id varchar(50) NOT NULL REFERENCES access_management.user_role_assignments ON DELETE CASCADE,
 scope_id varchar(50) NOT NULL REFERENCES access_management.access_scopes,
 PRIMARY KEY(assignment_id,scope_id)
);

CREATE TABLE access_management.user_privilege_scopes (
 assignment_id varchar(50) NOT NULL REFERENCES access_management.user_privilege_assignments ON DELETE CASCADE,
 scope_id varchar(50) NOT NULL REFERENCES access_management.access_scopes,
 PRIMARY KEY(assignment_id,scope_id)
);

CREATE TABLE access_management.access_audit_log (
 audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 action varchar(100) NOT NULL,
 target_type varchar(50) NOT NULL,
 target_id varchar(100) NOT NULL,
 performed_by varchar(100) NOT NULL,
 performed_at timestamptz NOT NULL DEFAULT now(),
 reason text NOT NULL,
 correlation_id varchar(100) NOT NULL,
 old_value jsonb,
 new_value jsonb
);
CREATE INDEX access_audit_target_idx
 ON access_management.access_audit_log(target_type,target_id,audit_id DESC);

CREATE TRIGGER access_audit_immutable BEFORE UPDATE OR DELETE
 ON access_management.access_audit_log
 FOR EACH ROW EXECUTE FUNCTION customer_management.reject_mutation();

INSERT INTO access_management.access_scopes(scope_id,scope_type)
VALUES ('SCP-SELF','SELF'),('SCP-PLATFORM','PLATFORM');

WITH catalogue(code,module,name,risk,scopes,description) AS (
 VALUES
 ('dashboard.platform.view','DASHBOARD','View platform dashboard','LOW',ARRAY['CUSTOMER','PLATFORM'],'View platform overview within assigned scope'),
 ('dashboard.operations.view','DASHBOARD','View operations dashboard','MEDIUM',ARRAY['CUSTOMER','PLATFORM'],'View operational metrics and activity'),
 ('workqueue.own.view','DASHBOARD','View own work queue','LOW',ARRAY['SELF'],'View drafts, rejected requests and assigned work'),
 ('notification.view','DASHBOARD','View notifications','LOW',ARRAY['SELF'],'View personal platform notifications'),
 ('customer.view','CUSTOMER','View customers','LOW',ARRAY['CUSTOMER','PLATFORM'],'List and view customer records'),
 ('customer.create','CUSTOMER','Create customer','MEDIUM',ARRAY['SELF','CUSTOMER','PLATFORM'],'Create customer onboarding drafts'),
 ('customer.edit','CUSTOMER','Edit customer','MEDIUM',ARRAY['SELF','CUSTOMER','PLATFORM'],'Edit customer data when workflow permits'),
 ('customer.provider.manage','CUSTOMER','Manage customer providers','HIGH',ARRAY['CUSTOMER','PLATFORM'],'Change customer cloud-provider associations'),
 ('customer.submit','CUSTOMER','Submit customer','MEDIUM',ARRAY['SELF','CUSTOMER','PLATFORM'],'Submit or resubmit customer requests'),
 ('customer.review','CUSTOMER','Review customer','HIGH',ARRAY['CUSTOMER','PLATFORM'],'Start and perform customer review'),
 ('customer.approve','CUSTOMER','Approve customer','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Approve or reject reviewed customer requests'),
 ('customer.activate','CUSTOMER','Activate customer','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Activate approved customers'),
 ('customer.suspend','CUSTOMER','Suspend customer','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Suspend or reactivate customers'),
 ('customer.deactivate','CUSTOMER','Deactivate customer','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Deactivate customers'),
 ('customer.history.view','CUSTOMER','View customer history','LOW',ARRAY['CUSTOMER','PLATFORM'],'View customer lifecycle history'),
 ('customer.audit.view','CUSTOMER','View customer audit','HIGH',ARRAY['CUSTOMER','PLATFORM'],'View customer audit records'),
 ('environment.view','ENVIRONMENT','View environments','LOW',ARRAY['CUSTOMER','PLATFORM'],'List and view environments'),
 ('environment.create','ENVIRONMENT','Create environment','MEDIUM',ARRAY['SELF','CUSTOMER','PLATFORM'],'Create environment requests'),
 ('environment.edit','ENVIRONMENT','Edit environment','MEDIUM',ARRAY['SELF','CUSTOMER','PLATFORM'],'Edit eligible environment requests'),
 ('environment.discover','ENVIRONMENT','Discover cloud resources','HIGH',ARRAY['CUSTOMER','PLATFORM'],'Run read-only cloud discovery'),
 ('environment.submit','ENVIRONMENT','Submit environment','MEDIUM',ARRAY['SELF','CUSTOMER','PLATFORM'],'Submit or resubmit environment requests'),
 ('environment.review','ENVIRONMENT','Review environment','HIGH',ARRAY['CUSTOMER','PLATFORM'],'Start and perform environment review'),
 ('environment.approve','ENVIRONMENT','Approve environment','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Approve or reject environment requests'),
 ('environment.activate','ENVIRONMENT','Activate environment','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Activate approved environment revisions'),
 ('environment.suspend','ENVIRONMENT','Suspend environment','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Suspend or reactivate environments'),
 ('environment.deactivate','ENVIRONMENT','Deactivate environment','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Deactivate environments'),
 ('environment.revision.manage','ENVIRONMENT','Manage environment revisions','HIGH',ARRAY['CUSTOMER','PLATFORM'],'Create and maintain environment revisions'),
 ('environment.history.view','ENVIRONMENT','View environment history','LOW',ARRAY['CUSTOMER','PLATFORM'],'View environment lifecycle history'),
 ('environment.audit.view','ENVIRONMENT','View environment audit','HIGH',ARRAY['CUSTOMER','PLATFORM'],'View environment audit records'),
 ('cluster.view','CLUSTER','View clusters','LOW',ARRAY['CUSTOMER','PLATFORM'],'View cluster requests and provisioned clusters'),
 ('cluster.create','CLUSTER','Create cluster request','MEDIUM',ARRAY['SELF','CUSTOMER','PLATFORM'],'Create cluster requests'),
 ('cluster.edit','CLUSTER','Edit cluster request','MEDIUM',ARRAY['SELF','CUSTOMER','PLATFORM'],'Edit eligible cluster requests'),
 ('cluster.submit','CLUSTER','Submit cluster request','MEDIUM',ARRAY['SELF','CUSTOMER','PLATFORM'],'Submit or resubmit cluster requests'),
 ('cluster.review','CLUSTER','Review cluster request','HIGH',ARRAY['CUSTOMER','PLATFORM'],'Start and perform cluster review'),
 ('cluster.approve','CLUSTER','Approve cluster request','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Approve or reject cluster requests'),
 ('cluster.plan','CLUSTER','Generate cluster plan','HIGH',ARRAY['CUSTOMER','PLATFORM'],'Generate and inspect infrastructure plans'),
 ('cluster.apply','CLUSTER','Apply cluster infrastructure','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Authorize or execute infrastructure apply'),
 ('cluster.retry','CLUSTER','Retry cluster operation','HIGH',ARRAY['CUSTOMER','PLATFORM'],'Retry failed cluster operations'),
 ('cluster.cancel','CLUSTER','Cancel cluster operation','HIGH',ARRAY['CUSTOMER','PLATFORM'],'Cancel eligible cluster operations'),
 ('cluster.decommission','CLUSTER','Decommission cluster','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Perform controlled cluster removal'),
 ('cluster.logs.view','CLUSTER','View cluster logs','MEDIUM',ARRAY['CUSTOMER','PLATFORM'],'View cluster execution logs'),
 ('cluster.history.view','CLUSTER','View cluster history','LOW',ARRAY['CUSTOMER','PLATFORM'],'View cluster lifecycle history'),
 ('cluster.audit.view','CLUSTER','View cluster audit','HIGH',ARRAY['CUSTOMER','PLATFORM'],'View cluster audit records'),
 ('blueprint.view','BLUEPRINT','View blueprints','LOW',ARRAY['CUSTOMER','PLATFORM'],'View cluster blueprints'),
 ('blueprint.create','BLUEPRINT','Create blueprint','HIGH',ARRAY['CUSTOMER','PLATFORM'],'Create blueprint drafts'),
 ('blueprint.edit','BLUEPRINT','Edit blueprint','HIGH',ARRAY['CUSTOMER','PLATFORM'],'Edit blueprint drafts and revisions'),
 ('blueprint.submit','BLUEPRINT','Submit blueprint','HIGH',ARRAY['CUSTOMER','PLATFORM'],'Submit blueprints for review'),
 ('blueprint.review','BLUEPRINT','Review blueprint','HIGH',ARRAY['CUSTOMER','PLATFORM'],'Review submitted blueprints'),
 ('blueprint.approve','BLUEPRINT','Approve blueprint','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Approve, reject or activate blueprints'),
 ('remediation.view','OPERATIONS','View remediation','MEDIUM',ARRAY['CUSTOMER','PLATFORM'],'View remediation requests'),
 ('remediation.request','OPERATIONS','Request remediation','HIGH',ARRAY['CUSTOMER','PLATFORM'],'Submit remediation requests'),
 ('remediation.review','OPERATIONS','Review remediation','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Approve or reject remediation'),
 ('remediation.execute','OPERATIONS','Execute remediation','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Execute approved remediation'),
 ('operations.view','OPERATIONS','View operations','MEDIUM',ARRAY['CUSTOMER','PLATFORM'],'View provisioning activity'),
 ('operations.logs.view','OPERATIONS','View operational logs','HIGH',ARRAY['CUSTOMER','PLATFORM'],'View platform execution logs'),
 ('operations.retry','OPERATIONS','Retry operations','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Retry eligible failed operations'),
 ('operations.cancel','OPERATIONS','Cancel operations','CRITICAL',ARRAY['CUSTOMER','PLATFORM'],'Cancel eligible operations'),
 ('event.view','OPERATIONS','View platform events','HIGH',ARRAY['PLATFORM'],'View infrastructure and platform events'),
 ('audit.platform.view','GOVERNANCE','View platform audit','CRITICAL',ARRAY['PLATFORM'],'View platform-wide audit information'),
 ('compliance.view','GOVERNANCE','View compliance','HIGH',ARRAY['CUSTOMER','PLATFORM'],'View compliance and policy findings'),
 ('user.view','ACCESS','View users','HIGH',ARRAY['PLATFORM'],'View platform users'),
 ('user.manage','ACCESS','Manage users','CRITICAL',ARRAY['PLATFORM'],'Create, update and disable users'),
 ('role.view','ACCESS','View roles','HIGH',ARRAY['PLATFORM'],'View roles and role privileges'),
 ('role.manage','ACCESS','Manage roles','CRITICAL',ARRAY['PLATFORM'],'Create, update and retire roles'),
 ('privilege.view','ACCESS','View privileges','HIGH',ARRAY['PLATFORM'],'View the privilege catalogue'),
 ('assignment.manage','ACCESS','Manage assignments','CRITICAL',ARRAY['PLATFORM'],'Manage role and privilege assignments'),
 ('scope.manage','ACCESS','Manage access scopes','CRITICAL',ARRAY['PLATFORM'],'Manage platform and customer scopes'),
 ('serviceaccount.manage','ACCESS','Manage service accounts','CRITICAL',ARRAY['PLATFORM'],'Manage service identities'),
 ('access.audit.view','ACCESS','View access audit','CRITICAL',ARRAY['PLATFORM'],'View access assignment history'),
 ('provider.configure','PLATFORM','Configure providers','CRITICAL',ARRAY['PLATFORM'],'Manage supported cloud providers'),
 ('environmenttype.configure','PLATFORM','Configure environment types','CRITICAL',ARRAY['PLATFORM'],'Manage environment types'),
 ('workflow.configure','PLATFORM','Configure workflows','CRITICAL',ARRAY['PLATFORM'],'Manage workflow policies'),
 ('notification.configure','PLATFORM','Configure notifications','HIGH',ARRAY['PLATFORM'],'Manage notification policies'),
 ('platform.configure','PLATFORM','Configure platform','CRITICAL',ARRAY['PLATFORM'],'Manage platform configuration')
)
INSERT INTO access_management.privileges(
 privilege_id,privilege_code,module_code,name,risk_level,scope_types,description
)
SELECT 'PRV-' || upper(substr(md5(code),1,24)),code,module,name,risk,scopes,description
FROM catalogue;

INSERT INTO access_management.roles(
 role_id,role_code,role_name,description,role_type,created_by
) VALUES
 ('ROL-CLOUD-ENGINEER','CLOUD_ENGINEER','Cloud Engineer',
  'Starter template for creating and submitting customer, environment and cluster requests.',
  'SYSTEM_TEMPLATE','SYSTEM'),
 ('ROL-PLATFORM-ARCHITECT','PLATFORM_ARCHITECT','Platform Architect',
  'Starter template for independent review, approval and governance.',
  'SYSTEM_TEMPLATE','SYSTEM'),
 ('ROL-PLATFORM-ADMIN','PLATFORM_ADMINISTRATOR','Platform Administrator',
  'Starter template for access administration and platform configuration.',
  'SYSTEM_TEMPLATE','SYSTEM');

WITH grants(role_code,privilege_code) AS (
 VALUES
 ('CLOUD_ENGINEER','dashboard.platform.view'),('CLOUD_ENGINEER','workqueue.own.view'),
 ('CLOUD_ENGINEER','notification.view'),('CLOUD_ENGINEER','customer.view'),
 ('CLOUD_ENGINEER','customer.create'),('CLOUD_ENGINEER','customer.edit'),
 ('CLOUD_ENGINEER','customer.provider.manage'),('CLOUD_ENGINEER','customer.submit'),
 ('CLOUD_ENGINEER','customer.history.view'),('CLOUD_ENGINEER','environment.view'),
 ('CLOUD_ENGINEER','environment.create'),('CLOUD_ENGINEER','environment.edit'),
 ('CLOUD_ENGINEER','environment.discover'),('CLOUD_ENGINEER','environment.submit'),
 ('CLOUD_ENGINEER','environment.revision.manage'),('CLOUD_ENGINEER','environment.history.view'),
 ('CLOUD_ENGINEER','cluster.view'),('CLOUD_ENGINEER','cluster.create'),
 ('CLOUD_ENGINEER','cluster.edit'),('CLOUD_ENGINEER','cluster.submit'),
 ('CLOUD_ENGINEER','cluster.logs.view'),('CLOUD_ENGINEER','cluster.history.view'),
 ('CLOUD_ENGINEER','blueprint.view'),('CLOUD_ENGINEER','remediation.view'),
 ('CLOUD_ENGINEER','remediation.request'),
 ('PLATFORM_ARCHITECT','dashboard.platform.view'),('PLATFORM_ARCHITECT','dashboard.operations.view'),
 ('PLATFORM_ARCHITECT','notification.view'),('PLATFORM_ARCHITECT','customer.view'),
 ('PLATFORM_ARCHITECT','customer.review'),('PLATFORM_ARCHITECT','customer.approve'),
 ('PLATFORM_ARCHITECT','customer.activate'),('PLATFORM_ARCHITECT','customer.suspend'),
 ('PLATFORM_ARCHITECT','customer.deactivate'),('PLATFORM_ARCHITECT','customer.history.view'),
 ('PLATFORM_ARCHITECT','customer.audit.view'),('PLATFORM_ARCHITECT','environment.view'),
 ('PLATFORM_ARCHITECT','environment.review'),('PLATFORM_ARCHITECT','environment.approve'),
 ('PLATFORM_ARCHITECT','environment.activate'),('PLATFORM_ARCHITECT','environment.suspend'),
 ('PLATFORM_ARCHITECT','environment.deactivate'),('PLATFORM_ARCHITECT','environment.history.view'),
 ('PLATFORM_ARCHITECT','environment.audit.view'),('PLATFORM_ARCHITECT','cluster.view'),
 ('PLATFORM_ARCHITECT','cluster.review'),('PLATFORM_ARCHITECT','cluster.approve'),
  ('PLATFORM_ARCHITECT','cluster.plan'),('PLATFORM_ARCHITECT','cluster.apply'),
  ('PLATFORM_ARCHITECT','cluster.decommission'),('PLATFORM_ARCHITECT','cluster.logs.view'),
 ('PLATFORM_ARCHITECT','cluster.history.view'),('PLATFORM_ARCHITECT','cluster.audit.view'),
 ('PLATFORM_ARCHITECT','blueprint.view'),('PLATFORM_ARCHITECT','blueprint.review'),
 ('PLATFORM_ARCHITECT','blueprint.approve'),('PLATFORM_ARCHITECT','remediation.view'),
 ('PLATFORM_ARCHITECT','remediation.review'),('PLATFORM_ARCHITECT','operations.view'),
 ('PLATFORM_ARCHITECT','operations.logs.view'),('PLATFORM_ARCHITECT','compliance.view'),
 ('PLATFORM_ADMINISTRATOR','dashboard.platform.view'),('PLATFORM_ADMINISTRATOR','dashboard.operations.view'),
 ('PLATFORM_ADMINISTRATOR','customer.view'),('PLATFORM_ADMINISTRATOR','environment.view'),
  ('PLATFORM_ADMINISTRATOR','cluster.view'),('PLATFORM_ADMINISTRATOR','cluster.apply'),
  ('PLATFORM_ADMINISTRATOR','cluster.decommission'),('PLATFORM_ADMINISTRATOR','blueprint.view'),
 ('PLATFORM_ADMINISTRATOR','remediation.view'),('PLATFORM_ADMINISTRATOR','operations.view'),
 ('PLATFORM_ADMINISTRATOR','operations.logs.view'),('PLATFORM_ADMINISTRATOR','operations.retry'),
 ('PLATFORM_ADMINISTRATOR','operations.cancel'),('PLATFORM_ADMINISTRATOR','event.view'),
 ('PLATFORM_ADMINISTRATOR','audit.platform.view'),('PLATFORM_ADMINISTRATOR','compliance.view'),
 ('PLATFORM_ADMINISTRATOR','user.view'),('PLATFORM_ADMINISTRATOR','user.manage'),
 ('PLATFORM_ADMINISTRATOR','role.view'),('PLATFORM_ADMINISTRATOR','role.manage'),
 ('PLATFORM_ADMINISTRATOR','privilege.view'),('PLATFORM_ADMINISTRATOR','assignment.manage'),
 ('PLATFORM_ADMINISTRATOR','scope.manage'),('PLATFORM_ADMINISTRATOR','serviceaccount.manage'),
 ('PLATFORM_ADMINISTRATOR','access.audit.view'),('PLATFORM_ADMINISTRATOR','provider.configure'),
 ('PLATFORM_ADMINISTRATOR','environmenttype.configure'),('PLATFORM_ADMINISTRATOR','workflow.configure'),
 ('PLATFORM_ADMINISTRATOR','notification.configure'),('PLATFORM_ADMINISTRATOR','platform.configure')
)
INSERT INTO access_management.role_privileges(role_id,privilege_id,effect,created_by)
SELECT r.role_id,p.privilege_id,'ALLOW','SYSTEM'
FROM grants g
JOIN access_management.roles r USING(role_code)
JOIN access_management.privileges p USING(privilege_code);

REVOKE ALL ON SCHEMA access_management FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA access_management FROM PUBLIC;
