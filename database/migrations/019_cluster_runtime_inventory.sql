BEGIN;

CREATE TABLE cluster_management.cluster_runtime_inventories (
 cluster_id varchar(50) PRIMARY KEY REFERENCES cluster_management.clusters,
 connector_id varchar(50) NOT NULL REFERENCES cluster_management.cluster_connectors,
 source_revision bigint NOT NULL CHECK(source_revision > 0),
 status varchar(20) NOT NULL CHECK(status IN ('READY','DEGRADED')),
 resources jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(resources)='array'),
 warning_events jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(warning_events)='array'),
 metrics jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(metrics)='object'),
 observed_at timestamptz NOT NULL,
 expires_at timestamptz NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(expires_at > observed_at)
);

CREATE INDEX cluster_runtime_inventories_observed_idx
 ON cluster_management.cluster_runtime_inventories(observed_at DESC);

REVOKE ALL ON cluster_management.cluster_runtime_inventories FROM PUBLIC;

DO $$
BEGIN
 IF EXISTS (SELECT FROM pg_roles WHERE rolname='navigan_api') THEN
  GRANT SELECT,INSERT,UPDATE
   ON cluster_management.cluster_runtime_inventories TO navigan_api;
 END IF;
END $$;

COMMIT;
