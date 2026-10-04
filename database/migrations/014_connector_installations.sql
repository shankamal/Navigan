ALTER TABLE cluster_management.cluster_connectors
 ADD COLUMN installation_status varchar(20) NOT NULL DEFAULT 'REQUESTED'
   CHECK(installation_status IN ('REQUESTED','RUNNING','SUCCEEDED','FAILED')),
 ADD COLUMN installation_execution_id varchar(255),
 ADD COLUMN installation_secret_arn varchar(2048),
 ADD COLUMN installation_failure_code varchar(100),
 ADD COLUMN installation_reason varchar(2000),
 ADD COLUMN installation_requested_at timestamptz NOT NULL DEFAULT now(),
 ADD COLUMN installation_completed_at timestamptz;

CREATE INDEX cluster_connector_installation_status_idx
 ON cluster_management.cluster_connectors(installation_status,installation_requested_at);
