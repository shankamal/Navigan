CREATE SCHEMA IF NOT EXISTS migration_management;

CREATE TABLE migration_management.migrations (
 migration_id varchar(50) PRIMARY KEY,
 customer_id varchar(50) NOT NULL
   REFERENCES customer_management.customers(customer_id),
 name varchar(100) NOT NULL,
 description text,
 source_platform varchar(40) NOT NULL CHECK(source_platform IN (
   'SELF_MANAGED_KUBERNETES','EKS','AKS','GKE','ECS'
 )),
 target_platform varchar(40) NOT NULL CHECK(target_platform IN (
   'SELF_MANAGED_KUBERNETES','EKS','AKS','GKE','ECS'
 )),
 source_configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
 target_configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
 migration_scope jsonb NOT NULL DEFAULT '{}'::jsonb,
 execution_mode varchar(30) NOT NULL DEFAULT 'ASSESSMENT_ONLY'
   CHECK(execution_mode IN ('ASSESSMENT_ONLY')),
 status varchar(30) NOT NULL DEFAULT 'DRAFT' CHECK(status IN (
   'DRAFT','SOURCE_ENROLLMENT_PENDING','INVENTORY_DISCOVERING',
   'INVENTORY_READY','DISCOVERY_PENDING','DISCOVERING','ASSESSING',
   'ASSESSMENT_READY','SUBMITTED','UNDER_REVIEW','APPROVED',
   'REJECTED','FAILED','CANCELLED'
 )),
 version bigint NOT NULL DEFAULT 1 CHECK(version > 0),
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_by varchar(100) NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(customer_id,name)
);

CREATE TABLE migration_management.migration_versions (
 migration_id varchar(50) NOT NULL
   REFERENCES migration_management.migrations(migration_id),
 version bigint NOT NULL,
 snapshot jsonb NOT NULL,
 change_reason text,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(migration_id,version)
);

CREATE TABLE migration_management.migration_connectors (
 connector_id varchar(50) PRIMARY KEY
   CHECK(connector_id ~ '^MGC-[0-9a-f]{32}$'),
 migration_id varchar(50) NOT NULL
   REFERENCES migration_management.migrations(migration_id),
 token_sha256 char(64) NOT NULL
   CHECK(token_sha256 ~ '^[0-9a-f]{64}$'),
 status varchar(20) NOT NULL DEFAULT 'ENROLLED'
   CHECK(status IN ('ENROLLED','ACTIVE','COMPLETED','REVOKED')),
 expires_at timestamptz NOT NULL,
 last_seen_at timestamptz,
 completed_at timestamptz,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 revoked_by varchar(100),
 revoked_at timestamptz,
 CHECK(expires_at > created_at),
 CHECK(
   (status='COMPLETED' AND completed_at IS NOT NULL)
   OR status<>'COMPLETED'
 ),
 CHECK(
   (status='REVOKED' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL)
   OR status<>'REVOKED'
 )
);

CREATE UNIQUE INDEX migration_connector_current_uq
 ON migration_management.migration_connectors(migration_id)
 WHERE status IN ('ENROLLED','ACTIVE');

REVOKE ALL ON migration_management.migration_connectors FROM PUBLIC;

CREATE TABLE migration_management.migration_source_catalogues (
 migration_id varchar(50) NOT NULL
   REFERENCES migration_management.migrations(migration_id),
 catalogue_version bigint NOT NULL CHECK(catalogue_version > 0),
 migration_version bigint NOT NULL CHECK(migration_version > 0),
 schema_version integer NOT NULL CHECK(schema_version > 0),
 observed_at timestamptz NOT NULL,
 source_kubernetes_version varchar(30) NOT NULL,
 inventory_digest varchar(64) NOT NULL
   CHECK(inventory_digest ~ '^[a-f0-9]{64}$'),
 node_count integer NOT NULL CHECK(node_count >= 0),
 architectures jsonb NOT NULL,
 namespaces jsonb NOT NULL,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(migration_id,catalogue_version)
);

CREATE TABLE migration_management.migration_source_inventories (
 migration_id varchar(50) NOT NULL
   REFERENCES migration_management.migrations(migration_id),
 inventory_version bigint NOT NULL CHECK(inventory_version > 0),
 migration_version bigint NOT NULL CHECK(migration_version > 0),
 schema_version integer NOT NULL CHECK(schema_version > 0),
 observed_at timestamptz NOT NULL,
 source_kubernetes_version varchar(30) NOT NULL,
 inventory_digest varchar(64) NOT NULL
   CHECK(inventory_digest ~ '^[a-f0-9]{64}$'),
 resource_count integer NOT NULL CHECK(resource_count > 0),
 resources jsonb NOT NULL,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(migration_id,inventory_version)
);

CREATE UNIQUE INDEX migration_source_inventory_digest_uq
 ON migration_management.migration_source_inventories(
   migration_id,
   inventory_digest
 );

REVOKE ALL
 ON migration_management.migration_source_inventories
 FROM PUBLIC;

CREATE TABLE migration_management.migration_assessments (
 migration_id varchar(50) NOT NULL
   REFERENCES migration_management.migrations(migration_id),
 assessment_version bigint NOT NULL CHECK(assessment_version > 0),
 migration_version bigint NOT NULL CHECK(migration_version > 0),
 report_schema_version integer NOT NULL
   CHECK(report_schema_version > 0),
 source_kubernetes_version varchar(30) NOT NULL,
 observed_at timestamptz NOT NULL,
 inventory_digest varchar(64) NOT NULL
   CHECK(inventory_digest ~ '^[a-f0-9]{64}$'),
 compatibility_score integer NOT NULL
   CHECK(compatibility_score BETWEEN 0 AND 100),
 contains_blockers boolean NOT NULL,
 inventory_summary jsonb NOT NULL,
 findings jsonb NOT NULL,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(migration_id,assessment_version)
);

CREATE TABLE migration_management.migration_status_history (
 history_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 migration_id varchar(50) NOT NULL
   REFERENCES migration_management.migrations(migration_id),
 previous_status varchar(30),
 new_status varchar(30) NOT NULL,
 changed_by varchar(100) NOT NULL,
 reason text,
 comments text,
 correlation_id varchar(100) NOT NULL,
 changed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE migration_management.migration_audit_log (
 audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 migration_id varchar(50) NOT NULL
   REFERENCES migration_management.migrations(migration_id),
 action varchar(100) NOT NULL,
 performed_by varchar(100) NOT NULL,
 correlation_id varchar(100) NOT NULL,
 old_value jsonb,
 new_value jsonb,
 occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX migrations_customer_idx
 ON migration_management.migrations(customer_id,status,updated_at DESC);

CREATE INDEX migration_history_idx
 ON migration_management.migration_status_history(migration_id,history_id);

CREATE INDEX migration_audit_idx
 ON migration_management.migration_audit_log(migration_id,audit_id);

DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY[
   'migration_versions',
   'migration_source_catalogues',
   'migration_assessments',
   'migration_status_history',
   'migration_audit_log'
 ] LOOP
  EXECUTE format(
   'CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON migration_management.%I FOR EACH ROW EXECUTE FUNCTION customer_management.reject_mutation()',
   t
  );
 END LOOP;
END $$;

REVOKE ALL ON SCHEMA migration_management FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA migration_management FROM PUBLIC;

WITH catalogue(code,module,name,risk,scopes,description) AS (
 VALUES
 ('migration.view','MIGRATION','View migrations','LOW',
  ARRAY['CUSTOMER','PLATFORM'],'View migration requests and assessments'),
 ('migration.create','MIGRATION','Create migration','MEDIUM',
  ARRAY['CUSTOMER','PLATFORM'],'Create assessment-only migration requests'),
 ('migration.edit','MIGRATION','Edit migration','MEDIUM',
  ARRAY['CUSTOMER','PLATFORM'],'Edit eligible migration requests'),
 ('migration.submit','MIGRATION','Submit migration','MEDIUM',
  ARRAY['CUSTOMER','PLATFORM'],'Submit migration assessments for review'),
 ('migration.review','MIGRATION','Review migration','HIGH',
  ARRAY['CUSTOMER','PLATFORM'],'Perform independent migration review'),
 ('migration.approve','MIGRATION','Approve migration','CRITICAL',
  ARRAY['CUSTOMER','PLATFORM'],'Approve or reject migration plans'),
 ('migration.history.view','MIGRATION','View migration history','LOW',
  ARRAY['CUSTOMER','PLATFORM'],'View migration lifecycle history'),
 ('migration.audit.view','MIGRATION','View migration audit','HIGH',
  ARRAY['CUSTOMER','PLATFORM'],'View migration audit records')
)
INSERT INTO access_management.privileges(
 privilege_id,privilege_code,module_code,name,
 risk_level,scope_types,description
)
SELECT
 'PRV-' || upper(substr(md5(code),1,24)),
 code,module,name,risk,scopes,description
FROM catalogue
ON CONFLICT (privilege_code) DO NOTHING;

WITH grants(role_code,privilege_code) AS (
 VALUES
 ('CLOUD_ENGINEER','migration.view'),
 ('CLOUD_ENGINEER','migration.create'),
 ('CLOUD_ENGINEER','migration.edit'),
 ('CLOUD_ENGINEER','migration.submit'),
 ('CLOUD_ENGINEER','migration.history.view'),
 ('PLATFORM_ARCHITECT','migration.view'),
 ('PLATFORM_ARCHITECT','migration.review'),
 ('PLATFORM_ARCHITECT','migration.approve'),
 ('PLATFORM_ARCHITECT','migration.history.view'),
 ('PLATFORM_ARCHITECT','migration.audit.view'),
 ('PLATFORM_ADMINISTRATOR','migration.view'),
 ('PLATFORM_ADMINISTRATOR','migration.audit.view')
)
INSERT INTO access_management.role_privileges(
 role_id,privilege_id,effect,created_by
)
SELECT r.role_id,p.privilege_id,'ALLOW','SYSTEM'
FROM grants g
JOIN access_management.roles r USING(role_code)
JOIN access_management.privileges p USING(privilege_code)
ON CONFLICT (role_id,privilege_id) DO NOTHING;
