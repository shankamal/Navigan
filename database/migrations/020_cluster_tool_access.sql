CREATE TABLE cluster_management.cluster_tool_tunnels (
 cluster_id varchar(50) PRIMARY KEY REFERENCES cluster_management.clusters,
 connector_id varchar(50) NOT NULL REFERENCES cluster_management.cluster_connectors,
 status varchar(20) NOT NULL CHECK(status IN ('CONNECTED','DISCONNECTED')),
 gateway_instance_id varchar(100) NOT NULL,
 connected_at timestamptz,
 last_seen_at timestamptz NOT NULL,
 expires_at timestamptz NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(expires_at > last_seen_at)
);
CREATE INDEX cluster_tool_tunnels_expiry_idx
 ON cluster_management.cluster_tool_tunnels(expires_at);

CREATE TABLE cluster_management.cluster_tool_sessions (
 session_id varchar(50) PRIMARY KEY,
 cluster_id varchar(50) NOT NULL REFERENCES cluster_management.clusters,
 customer_id varchar(50) NOT NULL REFERENCES customer_management.customers,
 user_id varchar(100) NOT NULL,
 tool_code varchar(30) NOT NULL
  CHECK(tool_code IN ('HEADLAMP','GRAFANA','PROMETHEUS','ARGOCD','WEBKUBECTL')),
 status varchar(20) NOT NULL
  CHECK(status IN ('ISSUED','ACTIVE','CLOSED','EXPIRED','REVOKED')),
 exchange_token_sha256 char(64),
 exchange_expires_at timestamptz NOT NULL,
 access_token_sha256 char(64),
 issued_at timestamptz NOT NULL DEFAULT now(),
 activated_at timestamptz,
 last_seen_at timestamptz,
 expires_at timestamptz NOT NULL,
 closed_at timestamptz,
 close_reason varchar(100),
 CHECK(exchange_expires_at <= expires_at),
 CHECK(expires_at > issued_at),
 CHECK(
   (status='ISSUED' AND exchange_token_sha256 IS NOT NULL)
   OR status<>'ISSUED'
 )
);
CREATE INDEX cluster_tool_sessions_user_idx
 ON cluster_management.cluster_tool_sessions(user_id,issued_at DESC);
CREATE INDEX cluster_tool_sessions_cluster_idx
 ON cluster_management.cluster_tool_sessions(cluster_id,issued_at DESC);
CREATE INDEX cluster_tool_sessions_expiry_idx
 ON cluster_management.cluster_tool_sessions(status,expires_at);

REVOKE ALL ON cluster_management.cluster_tool_tunnels FROM PUBLIC;
REVOKE ALL ON cluster_management.cluster_tool_sessions FROM PUBLIC;
