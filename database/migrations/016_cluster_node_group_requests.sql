CREATE TABLE cluster_management.cluster_node_group_requests (
 request_id varchar(50) PRIMARY KEY,
 cluster_id varchar(50) NOT NULL REFERENCES cluster_management.clusters,
 customer_id varchar(50) NOT NULL REFERENCES customer_management.customers,
 node_group jsonb NOT NULL,
 reason text NOT NULL,
 status varchar(30) NOT NULL CHECK(status IN (
   'DRAFT','SUBMITTED','PLAN_RUNNING','PLAN_READY','APPLYING',
   'ACTIVE','FAILED','REJECTED','CANCELLED'
 )),
 version bigint NOT NULL DEFAULT 1 CHECK(version > 0),
 plan_artifact_key text,
 plan_sha256 varchar(64),
 provider_execution_id text,
 execution_artifact_prefix text,
 workflow jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_by varchar(100) NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX cluster_node_group_requests_name_idx
 ON cluster_management.cluster_node_group_requests(cluster_id,(node_group->>'name'));

CREATE INDEX cluster_node_group_requests_cluster_idx
 ON cluster_management.cluster_node_group_requests(cluster_id,status,updated_at DESC);

CREATE INDEX cluster_node_group_requests_execution_idx
 ON cluster_management.cluster_node_group_requests(provider_execution_id)
 WHERE provider_execution_id IS NOT NULL;

REVOKE ALL ON cluster_management.cluster_node_group_requests FROM PUBLIC;
