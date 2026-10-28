BEGIN;
CREATE TABLE migration_management.workspace_collection_jobs (
 job_id varchar(40) PRIMARY KEY CHECK(job_id ~ '^COL-[a-f0-9]{32}$'),
 workspace_id varchar(40) NOT NULL,
 artifact_id varchar(68) NOT NULL,
 status varchar(20) NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts >= 0),
 lease_token varchar(32),
 lease_until timestamptz,
 error_code varchar(60),
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(workspace_id,artifact_id),
 FOREIGN KEY(workspace_id,artifact_id) REFERENCES migration_management.workspace_artifacts(workspace_id,artifact_id)
);
CREATE INDEX workspace_collection_claim ON migration_management.workspace_collection_jobs(status,lease_until,created_at);
COMMIT;
