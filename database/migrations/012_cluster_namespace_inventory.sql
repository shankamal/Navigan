CREATE TABLE cluster_management.cluster_namespace_inventories (
 cluster_id varchar(50) PRIMARY KEY REFERENCES cluster_management.clusters,
 status varchar(20) NOT NULL DEFAULT 'NOT_CONFIGURED'
   CHECK(status IN ('NOT_CONFIGURED','SYNCING','READY','STALE','FAILED')),
 source varchar(30) NOT NULL DEFAULT 'IN_CLUSTER_CONNECTOR'
   CHECK(source IN ('IN_CLUSTER_CONNECTOR')),
 source_revision bigint NOT NULL DEFAULT 0 CHECK(source_revision >= 0),
 observed_at timestamptz,
 expires_at timestamptz,
 failure_code varchar(100),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(expires_at IS NULL OR observed_at IS NOT NULL),
 CHECK(expires_at IS NULL OR expires_at > observed_at),
 CHECK(status <> 'READY' OR (observed_at IS NOT NULL AND expires_at IS NOT NULL))
);

CREATE TABLE cluster_management.cluster_namespaces (
 cluster_id varchar(50) NOT NULL REFERENCES cluster_management.clusters,
 namespace varchar(253) NOT NULL,
 is_system boolean NOT NULL DEFAULT false,
 labels jsonb NOT NULL DEFAULT '{}'::jsonb,
 source_revision bigint NOT NULL CHECK(source_revision > 0),
 observed_at timestamptz NOT NULL,
 PRIMARY KEY(cluster_id,namespace),
 CHECK(namespace ~ '^[a-z0-9]([-a-z0-9]*[a-z0-9])?$'),
 CHECK(jsonb_typeof(labels)='object')
);
CREATE INDEX cluster_namespaces_observed_idx
 ON cluster_management.cluster_namespaces(cluster_id,observed_at DESC);

REVOKE ALL ON cluster_management.cluster_namespace_inventories,
 cluster_management.cluster_namespaces FROM PUBLIC;
