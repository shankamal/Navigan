BEGIN;

CREATE TABLE cluster_management.upgrade_plans (
 plan_id varchar(50) PRIMARY KEY,
 cluster_id varchar(50) NOT NULL REFERENCES cluster_management.clusters,
 customer_id varchar(50) NOT NULL REFERENCES customer_management.customers,
 provider varchar(20) NOT NULL CHECK(provider IN ('EKS')),
 current_version varchar(30) NOT NULL,
 target_version varchar(30) NOT NULL,
 strategy varchar(40) NOT NULL CHECK(strategy IN ('PROVIDER_MANAGED_ROLLING')),
 status varchar(30) NOT NULL CHECK(status IN (
   'DRAFT','SUBMITTED','APPROVED','SCHEDULED','EXECUTING',
   'SUCCEEDED','FAILED','REJECTED','CANCELLED'
 )),
 scheduled_for timestamptz,
 change_reason text NOT NULL,
 readiness_evidence jsonb NOT NULL,
 execution jsonb NOT NULL DEFAULT '{}'::jsonb,
 version bigint NOT NULL DEFAULT 1 CHECK(version > 0),
 submitted_by varchar(100),
 submitted_at timestamptz,
 approved_by varchar(100),
 approved_at timestamptz,
 created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_by varchar(100) NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT upgrade_plan_version_change CHECK(current_version <> target_version)
);

CREATE UNIQUE INDEX upgrade_plans_active_cluster_idx
 ON cluster_management.upgrade_plans(cluster_id)
 WHERE status IN ('DRAFT','SUBMITTED','APPROVED','SCHEDULED','EXECUTING');

CREATE INDEX upgrade_plans_history_idx
 ON cluster_management.upgrade_plans(cluster_id,created_at DESC);

REVOKE ALL ON cluster_management.upgrade_plans FROM PUBLIC;

COMMIT;
