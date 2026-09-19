CREATE TABLE cluster_management.cluster_identity_integrations (
 cluster_id varchar(50) PRIMARY KEY REFERENCES cluster_management.clusters,
 provider varchar(20) NOT NULL DEFAULT 'EKS' CHECK(provider IN ('EKS')),
 status varchar(30) NOT NULL DEFAULT 'NOT_CONFIGURED' CHECK(status IN (
   'NOT_CONFIGURED','PENDING','RECONCILING','READY','DRIFTED','FAILED','UNSUPPORTED'
 )),
 issuer text,
 audience varchar(255),
 username_claim varchar(100),
 groups_claim varchar(100),
 username_prefix varchar(100),
 groups_prefix varchar(100),
 configuration_fingerprint varchar(64),
 desired_revision bigint NOT NULL DEFAULT 1 CHECK(desired_revision > 0),
 applied_revision bigint CHECK(applied_revision IS NULL OR applied_revision > 0),
 last_verified_at timestamptz,
 failure_code varchar(100),
 version bigint NOT NULL DEFAULT 1 CHECK(version > 0),
 updated_by varchar(100) NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(configuration_fingerprint IS NULL OR configuration_fingerprint ~ '^[0-9a-f]{64}$'),
 CHECK(
   status <> 'READY'
   OR (
     issuer IS NOT NULL AND audience IS NOT NULL
     AND username_claim IS NOT NULL AND groups_claim IS NOT NULL
     AND configuration_fingerprint IS NOT NULL
     AND applied_revision = desired_revision
     AND last_verified_at IS NOT NULL
   )
 )
);
CREATE INDEX cluster_identity_status_idx
 ON cluster_management.cluster_identity_integrations(status,updated_at DESC);

ALTER TABLE cluster_management.clusters
 ADD CONSTRAINT clusters_identity_customer_uq UNIQUE(cluster_id,customer_id);

CREATE TABLE access_management.kubernetes_access_profiles (
 profile_id varchar(50) PRIMARY KEY,
 profile_code varchar(100) NOT NULL UNIQUE,
 profile_name varchar(255) NOT NULL,
 description text NOT NULL DEFAULT '',
 scope_type varchar(20) NOT NULL CHECK(scope_type IN ('NAMESPACE','CLUSTER')),
 permissions jsonb NOT NULL DEFAULT '[]'::jsonb,
 status varchar(20) NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','RETIRED')),
 version bigint NOT NULL DEFAULT 1 CHECK(version > 0),
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_by varchar(100),
 updated_at timestamptz,
 CHECK(jsonb_typeof(permissions)='array')
);

CREATE TABLE access_management.kubernetes_access_assignments (
 assignment_id varchar(50) PRIMARY KEY,
 subject_type varchar(20) NOT NULL CHECK(subject_type IN ('USER','GROUP')),
 subject_id varchar(255) NOT NULL,
 profile_id varchar(50) NOT NULL REFERENCES access_management.kubernetes_access_profiles,
 customer_id varchar(50) NOT NULL REFERENCES customer_management.customers,
 cluster_id varchar(50),
 namespace varchar(253),
 valid_from timestamptz NOT NULL DEFAULT now(),
 valid_until timestamptz,
 status varchar(20) NOT NULL DEFAULT 'ACTIVE'
   CHECK(status IN ('PENDING','ACTIVE','REVOKED','EXPIRED')),
 reason text NOT NULL,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 revoked_by varchar(100),
 revoked_at timestamptz,
 FOREIGN KEY(cluster_id,customer_id)
   REFERENCES cluster_management.clusters(cluster_id,customer_id),
 CHECK(valid_until IS NULL OR valid_until > valid_from),
 CHECK(namespace IS NULL OR namespace ~ '^[a-z0-9]([-a-z0-9]*[a-z0-9])?$'),
 CHECK(
   (status='REVOKED' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL)
   OR (status<>'REVOKED' AND revoked_by IS NULL AND revoked_at IS NULL)
 )
);
CREATE INDEX kubernetes_access_customer_idx
 ON access_management.kubernetes_access_assignments(customer_id,status);
CREATE INDEX kubernetes_access_cluster_idx
 ON access_management.kubernetes_access_assignments(cluster_id,status)
 WHERE cluster_id IS NOT NULL;
CREATE UNIQUE INDEX kubernetes_access_active_uq
 ON access_management.kubernetes_access_assignments(
   subject_type,subject_id,profile_id,customer_id,
   coalesce(cluster_id,''),coalesce(namespace,'')
 )
 WHERE status IN ('PENDING','ACTIVE');

CREATE TABLE cluster_management.cluster_access_reconciliations (
 reconciliation_id varchar(50) PRIMARY KEY,
 cluster_id varchar(50) NOT NULL REFERENCES cluster_management.clusters,
 idempotency_key varchar(128) NOT NULL,
 desired_revision bigint NOT NULL CHECK(desired_revision > 0),
 status varchar(30) NOT NULL CHECK(status IN (
   'PENDING','RUNNING','SUCCEEDED','FAILED','CANCELLED'
 )),
 execution_id text,
 initiated_by varchar(100) NOT NULL,
 started_at timestamptz,
 completed_at timestamptz,
 failure_code varchar(100),
 result jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(cluster_id,idempotency_key),
 CHECK(jsonb_typeof(result)='object')
);
CREATE UNIQUE INDEX cluster_access_reconciliation_running_uq
 ON cluster_management.cluster_access_reconciliations(cluster_id)
 WHERE status IN ('PENDING','RUNNING');

CREATE TABLE cluster_management.webkubectl_sessions (
 session_id varchar(50) PRIMARY KEY,
 cluster_id varchar(50) NOT NULL REFERENCES cluster_management.clusters,
 customer_id varchar(50) NOT NULL REFERENCES customer_management.customers,
 user_id varchar(100) NOT NULL,
 namespace varchar(253),
 profile_code varchar(100) NOT NULL,
 status varchar(20) NOT NULL CHECK(status IN ('ACTIVE','CLOSED','EXPIRED','REVOKED')),
 issued_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL,
 revoked_by varchar(100),
 revoked_at timestamptz,
 close_reason varchar(100),
 CHECK(expires_at > issued_at),
 CHECK(namespace IS NULL OR namespace ~ '^[a-z0-9]([-a-z0-9]*[a-z0-9])?$'),
 CHECK(
   (status='REVOKED' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL)
   OR status<>'REVOKED'
 )
);
CREATE INDEX webkubectl_user_sessions_idx
 ON cluster_management.webkubectl_sessions(user_id,issued_at DESC);
CREATE INDEX webkubectl_cluster_sessions_idx
 ON cluster_management.webkubectl_sessions(cluster_id,issued_at DESC);

WITH catalogue(code,module,name,risk,scopes,description) AS (
 VALUES
 ('cluster.identity.view','CLUSTER','View cluster identity integration','MEDIUM',
  ARRAY['CUSTOMER','PLATFORM','RESOURCE'],'View sanitized cluster identity integration state'),
 ('cluster.identity.reconcile','CLUSTER','Reconcile cluster identity integration','CRITICAL',
  ARRAY['CUSTOMER','PLATFORM','RESOURCE'],'Request governed OIDC and Kubernetes RBAC reconciliation'),
 ('cluster.access.view','ACCESS','View Kubernetes access','HIGH',
  ARRAY['CUSTOMER','PLATFORM','RESOURCE'],'View effective Kubernetes access assignments'),
 ('cluster.access.manage','ACCESS','Manage Kubernetes access','CRITICAL',
  ARRAY['CUSTOMER','PLATFORM','RESOURCE'],'Create and revoke governed Kubernetes access assignments'),
 ('cluster.dashboard.view','CLUSTER','View Kubernetes dashboard','MEDIUM',
  ARRAY['CUSTOMER','PLATFORM','RESOURCE'],'View sanitized Kubernetes inventory and health'),
 ('cluster.webkubectl.open','CLUSTER','Open WebKubectl','HIGH',
  ARRAY['CUSTOMER','PLATFORM','RESOURCE'],'Open a short-lived user-specific Kubernetes terminal session'),
 ('cluster.webkubectl.audit','GOVERNANCE','Audit WebKubectl sessions','CRITICAL',
  ARRAY['CUSTOMER','PLATFORM','RESOURCE'],'View WebKubectl session audit records')
)
INSERT INTO access_management.privileges(
 privilege_id,privilege_code,module_code,name,risk_level,scope_types,description
)
SELECT 'PRV-' || upper(substr(md5(code),1,24)),code,module,name,risk,scopes,description
FROM catalogue
ON CONFLICT(privilege_code) DO NOTHING;

WITH grants(role_code,privilege_code) AS (
 VALUES
 ('CLOUD_ENGINEER','cluster.identity.view'),
 ('CLOUD_ENGINEER','cluster.access.view'),
 ('CLOUD_ENGINEER','cluster.dashboard.view'),
 ('CLOUD_ENGINEER','cluster.webkubectl.open'),
 ('PLATFORM_ARCHITECT','cluster.identity.view'),
 ('PLATFORM_ARCHITECT','cluster.identity.reconcile'),
 ('PLATFORM_ARCHITECT','cluster.access.view'),
 ('PLATFORM_ARCHITECT','cluster.access.manage'),
 ('PLATFORM_ARCHITECT','cluster.dashboard.view'),
 ('PLATFORM_ARCHITECT','cluster.webkubectl.open'),
 ('PLATFORM_ARCHITECT','cluster.webkubectl.audit'),
 ('PLATFORM_ADMINISTRATOR','cluster.identity.view'),
 ('PLATFORM_ADMINISTRATOR','cluster.identity.reconcile'),
 ('PLATFORM_ADMINISTRATOR','cluster.access.view'),
 ('PLATFORM_ADMINISTRATOR','cluster.access.manage'),
 ('PLATFORM_ADMINISTRATOR','cluster.dashboard.view'),
 ('PLATFORM_ADMINISTRATOR','cluster.webkubectl.open'),
 ('PLATFORM_ADMINISTRATOR','cluster.webkubectl.audit')
)
INSERT INTO access_management.role_privileges(role_id,privilege_id,effect,created_by)
SELECT role.role_id,privilege.privilege_id,'ALLOW','SYSTEM'
FROM grants
JOIN access_management.roles role USING(role_code)
JOIN access_management.privileges privilege USING(privilege_code)
ON CONFLICT DO NOTHING;

REVOKE ALL ON ALL TABLES IN SCHEMA cluster_management FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA access_management FROM PUBLIC;
