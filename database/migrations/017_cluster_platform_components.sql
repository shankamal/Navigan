BEGIN;

CREATE TABLE cluster_management.cluster_platform_component_inventories (
 cluster_id varchar(50) PRIMARY KEY REFERENCES cluster_management.clusters,
 connector_id varchar(50) NOT NULL REFERENCES cluster_management.cluster_connectors,
 source_revision bigint NOT NULL CHECK(source_revision > 0),
 status varchar(20) NOT NULL CHECK(status IN ('READY','DEGRADED')),
 observed_at timestamptz NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE cluster_management.cluster_platform_components (
 cluster_id varchar(50) NOT NULL REFERENCES cluster_management.clusters,
 component_code varchar(80) NOT NULL,
 status varchar(20) NOT NULL CHECK(status IN ('READY','PROGRESSING','DEGRADED','MISSING')),
 version varchar(100),
 sync_status varchar(40),
 health_status varchar(40),
 observed_at timestamptz NOT NULL,
 source_revision bigint NOT NULL CHECK(source_revision > 0),
 PRIMARY KEY(cluster_id,component_code)
);

CREATE INDEX cluster_platform_components_status_idx
 ON cluster_management.cluster_platform_components(cluster_id,status);

REVOKE ALL ON cluster_management.cluster_platform_component_inventories FROM PUBLIC;
REVOKE ALL ON cluster_management.cluster_platform_components FROM PUBLIC;

COMMIT;
