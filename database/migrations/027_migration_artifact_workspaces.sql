BEGIN;
CREATE TABLE migration_management.artifact_workspaces (
 workspace_id varchar(40) PRIMARY KEY CHECK(workspace_id ~ '^AWS-[a-f0-9]{32}$'),
 migration_id varchar(50) NOT NULL REFERENCES migration_management.migrations(migration_id),
 customer_id varchar(50) NOT NULL REFERENCES customer_management.customers(customer_id),
 inventory_digest varchar(128) NOT NULL,
 inventory_version bigint NOT NULL,
 source_cluster_id varchar(50) NOT NULL,
 migration_version bigint NOT NULL,
 status varchar(30) NOT NULL CHECK(status IN ('PLANNED','COLLECTING','PARTIAL','COLLECTED','VALIDATED','FAILED')),
 namespaces jsonb NOT NULL CHECK(jsonb_typeof(namespaces)='array'),
 manifest jsonb NOT NULL CHECK(jsonb_typeof(manifest)='object'),
 bucket_name text NOT NULL,
 manifest_key text NOT NULL UNIQUE,
 manifest_version text NOT NULL,
 manifest_sha256 char(64) NOT NULL CHECK(manifest_sha256 ~ '^[a-f0-9]{64}$'),
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX artifact_workspaces_migration ON migration_management.artifact_workspaces(migration_id,created_at DESC);
CREATE TABLE migration_management.workspace_artifacts (
 workspace_id varchar(40) NOT NULL REFERENCES migration_management.artifact_workspaces(workspace_id),
 artifact_id varchar(68) NOT NULL,
 kind varchar(40) NOT NULL,
 status varchar(40) NOT NULL,
 provenance jsonb NOT NULL,
 workload_links jsonb NOT NULL CHECK(jsonb_typeof(workload_links)='array'),
 object_key text,
 object_version text,
 sha256 char(64),
 size_bytes bigint CHECK(size_bytes >= 0),
 validation jsonb NOT NULL DEFAULT '{}',
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(workspace_id,artifact_id)
);
COMMIT;
