CREATE TABLE cluster_management.github_app_connections (
 connection_id varchar(50) PRIMARY KEY,
 customer_id varchar(50) NOT NULL REFERENCES customer_management.customers,
 organization_login varchar(39) NOT NULL,
 installation_id bigint,
 status varchar(30) NOT NULL CHECK(status IN (
   'AUTHORIZATION_REQUIRED','ACTIVE','SUSPENDED','REVOKED'
 )),
 permissions jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_by varchar(100) NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(customer_id,organization_login),
 UNIQUE(installation_id)
);

CREATE TABLE cluster_management.github_app_authorization_states (
 state_sha256 varchar(64) PRIMARY KEY,
 connection_id varchar(50) NOT NULL
   REFERENCES cluster_management.github_app_connections(connection_id),
 requested_by varchar(100) NOT NULL,
 expires_at timestamptz NOT NULL,
 consumed_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE cluster_management.cluster_system_repositories (
 cluster_id varchar(50) PRIMARY KEY
   REFERENCES cluster_management.clusters(cluster_id),
 connection_id varchar(50)
   REFERENCES cluster_management.github_app_connections(connection_id),
 provider varchar(20) NOT NULL DEFAULT 'GITHUB'
   CHECK(provider IN ('GITHUB')),
 organization_login varchar(39) NOT NULL,
 repository_name varchar(100) NOT NULL,
 repository_id bigint,
 repository_url text,
 default_branch varchar(100) NOT NULL DEFAULT 'main',
 status varchar(30) NOT NULL CHECK(status IN (
   'AUTHORIZATION_REQUIRED','READY_TO_PROVISION','PROVISIONING','ACTIVE','FAILED'
 )),
 last_error_code varchar(100),
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_by varchar(100) NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(organization_login,repository_name)
);

CREATE INDEX github_connections_customer_idx
 ON cluster_management.github_app_connections(customer_id,status,organization_login);
CREATE INDEX github_authorization_expiry_idx
 ON cluster_management.github_app_authorization_states(expires_at)
 WHERE consumed_at IS NULL;
CREATE INDEX system_repositories_connection_idx
 ON cluster_management.cluster_system_repositories(connection_id,status);

REVOKE ALL ON cluster_management.github_app_connections FROM PUBLIC;
REVOKE ALL ON cluster_management.github_app_authorization_states FROM PUBLIC;
REVOKE ALL ON cluster_management.cluster_system_repositories FROM PUBLIC;
