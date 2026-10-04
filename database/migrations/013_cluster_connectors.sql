CREATE TABLE cluster_management.cluster_connectors (
 connector_id varchar(50) PRIMARY KEY,
 cluster_id varchar(50) NOT NULL REFERENCES cluster_management.clusters,
 token_sha256 char(64) NOT NULL,
 status varchar(20) NOT NULL DEFAULT 'ENROLLED'
   CHECK(status IN ('ENROLLED','ACTIVE','STALE','REVOKED')),
 last_seen_at timestamptz,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 revoked_by varchar(100),
 revoked_at timestamptz,
 CHECK(token_sha256 ~ '^[0-9a-f]{64}$'),
 CHECK(
   (status='REVOKED' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL)
   OR status<>'REVOKED'
 )
);
CREATE UNIQUE INDEX cluster_connector_current_uq
 ON cluster_management.cluster_connectors(cluster_id)
 WHERE status IN ('ENROLLED','ACTIVE','STALE');

ALTER TABLE cluster_management.cluster_namespace_inventories
 ADD COLUMN connector_id varchar(50)
 REFERENCES cluster_management.cluster_connectors;

REVOKE ALL ON cluster_management.cluster_connectors FROM PUBLIC;
