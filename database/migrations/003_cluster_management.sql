CREATE SCHEMA IF NOT EXISTS cluster_management;

CREATE TABLE cluster_management.clusters (
 cluster_id varchar(50) PRIMARY KEY,
 customer_id varchar(50) NOT NULL REFERENCES customer_management.customers,
 environment_id varchar(50) NOT NULL REFERENCES environment_management.environments,
 environment_approved_version bigint NOT NULL,
 platform varchar(20) NOT NULL CHECK(platform IN ('EKS')),
 cluster_name varchar(100) NOT NULL,
 configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
 provisioning_role_arn text NOT NULL,
 external_id_secret_arn text NOT NULL,
 terraform_module_version varchar(50) NOT NULL,
 terraform_state_key text NOT NULL,
 status varchar(30) NOT NULL CHECK(status IN (
   'DRAFT','SUBMITTED','UNDER_REVIEW','APPROVED','PLAN_RUNNING','PLAN_READY',
   'APPLYING','ACTIVE','FAILED','REJECTED','CANCELLED'
 )),
 version bigint NOT NULL DEFAULT 1 CHECK(version > 0),
 plan_artifact_key text,
 plan_sha256 varchar(64),
 provider_execution_id text,
 execution_artifact_prefix text,
 outputs jsonb NOT NULL DEFAULT '{}'::jsonb,
 workflow jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_by varchar(100) NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(environment_id,environment_approved_version)
   REFERENCES environment_management.environment_versions(environment_id,version),
 UNIQUE(customer_id,cluster_name)
);

CREATE TABLE cluster_management.cluster_versions (
 cluster_id varchar(50) NOT NULL REFERENCES cluster_management.clusters,
 version bigint NOT NULL,
 snapshot jsonb NOT NULL,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 change_reason text,
 PRIMARY KEY(cluster_id,version)
);

CREATE TABLE cluster_management.cluster_status_history (
 history_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 cluster_id varchar(50) NOT NULL REFERENCES cluster_management.clusters,
 previous_status varchar(30),
 new_status varchar(30) NOT NULL,
 changed_by varchar(100) NOT NULL,
 reason text,
 comments text,
 correlation_id varchar(100) NOT NULL,
 changed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE cluster_management.cluster_audit_log (
 audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 cluster_id varchar(50) NOT NULL REFERENCES cluster_management.clusters,
 action varchar(100) NOT NULL,
 performed_by varchar(100) NOT NULL,
 correlation_id varchar(100) NOT NULL,
 old_value jsonb,
 new_value jsonb,
 occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX clusters_customer_idx ON cluster_management.clusters(customer_id,status,updated_at DESC);
CREATE INDEX clusters_environment_idx ON cluster_management.clusters(environment_id,environment_approved_version);
CREATE INDEX clusters_execution_idx ON cluster_management.clusters(provider_execution_id)
 WHERE provider_execution_id IS NOT NULL;
CREATE INDEX cluster_history_idx ON cluster_management.cluster_status_history(cluster_id,history_id);
CREATE INDEX cluster_audit_idx ON cluster_management.cluster_audit_log(cluster_id,audit_id);

DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['cluster_versions','cluster_status_history','cluster_audit_log'] LOOP
  EXECUTE format(
   'CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON cluster_management.%I FOR EACH ROW EXECUTE FUNCTION customer_management.reject_mutation()',
   t
  );
 END LOOP;
END $$;

REVOKE ALL ON SCHEMA cluster_management FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA cluster_management FROM PUBLIC;
