BEGIN;

CREATE TABLE migration_management.source_clusters (
 source_cluster_id varchar(50) PRIMARY KEY
   CHECK(source_cluster_id ~ '^SRC-[0-9a-f]{32}$'),
 customer_id varchar(50) NOT NULL
   REFERENCES customer_management.customers(customer_id),
 name varchar(100) NOT NULL,
 distribution varchar(100),
 location_type varchar(20) NOT NULL
   CHECK(location_type IN ('CLOUD','ON_PREMISES','OTHER')),
 cloud_provider varchar(20)
   CHECK(cloud_provider IN ('AWS','AZURE','GCP','OCI','OTHER')),
 region varchar(64),
 registration_method varchar(30) NOT NULL
   CHECK(registration_method IN (
     'LOCAL_KUBECONFIG','GITOPS','PROVIDER_AUTOMATION'
   )),
 status varchar(30) NOT NULL DEFAULT 'PENDING_ENROLLMENT'
   CHECK(status IN (
     'PENDING_ENROLLMENT','CONNECTED','STALE','REVOKED'
   )),
 version bigint NOT NULL DEFAULT 1 CHECK(version > 0),
 last_connected_at timestamptz,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_by varchar(100) NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(customer_id,name),
 CHECK(
   (location_type='CLOUD' AND cloud_provider IS NOT NULL)
   OR (location_type<>'CLOUD' AND cloud_provider IS NULL)
 )
);

CREATE TABLE migration_management.source_cluster_enrollments (
 enrollment_id varchar(50) PRIMARY KEY
   CHECK(enrollment_id ~ '^SCE-[0-9a-f]{32}$'),
 source_cluster_id varchar(50) NOT NULL
   REFERENCES migration_management.source_clusters(source_cluster_id),
 token_sha256 char(64) NOT NULL
   CHECK(token_sha256 ~ '^[0-9a-f]{64}$'),
 status varchar(20) NOT NULL DEFAULT 'ISSUED'
   CHECK(status IN ('ISSUED','CONSUMED','EXPIRED','REVOKED')),
 expires_at timestamptz NOT NULL,
 consumed_at timestamptz,
 revoked_at timestamptz,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK(expires_at > created_at),
 CHECK(
   (status='CONSUMED' AND consumed_at IS NOT NULL)
   OR status<>'CONSUMED'
 ),
 CHECK(
   (status='REVOKED' AND revoked_at IS NOT NULL)
   OR status<>'REVOKED'
 )
);

CREATE UNIQUE INDEX source_cluster_current_enrollment_uq
 ON migration_management.source_cluster_enrollments(source_cluster_id)
 WHERE status='ISSUED';

CREATE TABLE migration_management.source_cluster_connectors (
 connector_id varchar(50) PRIMARY KEY
   CHECK(connector_id ~ '^SCC-[0-9a-f]{32}$'),
 source_cluster_id varchar(50) NOT NULL
   REFERENCES migration_management.source_clusters(source_cluster_id),
 token_sha256 char(64) NOT NULL
   CHECK(token_sha256 ~ '^[0-9a-f]{64}$'),
 status varchar(20) NOT NULL DEFAULT 'ACTIVE'
   CHECK(status IN ('ACTIVE','STALE','REVOKED')),
 expires_at timestamptz NOT NULL,
 last_seen_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 revoked_at timestamptz,
 CHECK(expires_at > created_at),
 CHECK(
   (status='REVOKED' AND revoked_at IS NOT NULL)
   OR status<>'REVOKED'
 )
);

CREATE UNIQUE INDEX source_cluster_active_connector_uq
 ON migration_management.source_cluster_connectors(source_cluster_id)
 WHERE status='ACTIVE';

CREATE INDEX source_clusters_customer_status_idx
 ON migration_management.source_clusters(
   customer_id,
   status,
   updated_at DESC
 );

CREATE TABLE migration_management.source_cluster_audit_log (
 audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 source_cluster_id varchar(50) NOT NULL
   REFERENCES migration_management.source_clusters(source_cluster_id),
 action varchar(100) NOT NULL,
 performed_by varchar(100) NOT NULL,
 correlation_id varchar(100) NOT NULL,
 details jsonb NOT NULL DEFAULT '{}'::jsonb,
 occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER immutable
 BEFORE UPDATE OR DELETE
 ON migration_management.source_cluster_audit_log
 FOR EACH ROW
 EXECUTE FUNCTION customer_management.reject_mutation();

REVOKE ALL ON migration_management.source_clusters FROM PUBLIC;
REVOKE ALL ON migration_management.source_cluster_enrollments FROM PUBLIC;
REVOKE ALL ON migration_management.source_cluster_connectors FROM PUBLIC;
REVOKE ALL ON migration_management.source_cluster_audit_log FROM PUBLIC;

DO $$
BEGIN
 IF EXISTS (SELECT FROM pg_roles WHERE rolname='navigan_api') THEN
  GRANT SELECT,INSERT,UPDATE
   ON migration_management.source_clusters TO navigan_api;
  GRANT SELECT,INSERT,UPDATE
   ON migration_management.source_cluster_enrollments,
      migration_management.source_cluster_connectors TO navigan_api;
  GRANT SELECT,INSERT
   ON migration_management.source_cluster_audit_log TO navigan_api;
  GRANT USAGE ON ALL SEQUENCES
   IN SCHEMA migration_management TO navigan_api;
 END IF;
END $$;

COMMIT;
