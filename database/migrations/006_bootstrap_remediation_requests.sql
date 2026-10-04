CREATE TABLE environment_management.bootstrap_remediation_requests (
 request_id varchar(50) PRIMARY KEY,
 customer_id varchar(50) NOT NULL REFERENCES customer_management.customers,
 account_id varchar(12) NOT NULL CHECK(account_id ~ '^[0-9]{12}$'),
 region varchar(32) NOT NULL,
 discovery_role_arn text NOT NULL,
 missing_resources jsonb NOT NULL CHECK(jsonb_typeof(missing_resources)='array'),
 requested_actions jsonb NOT NULL CHECK(jsonb_typeof(requested_actions)='array'),
 status varchar(30) NOT NULL CHECK(status IN ('REQUESTED','APPROVED','REJECTED','PLAN_RUNNING','PLAN_READY','APPLY_RUNNING','COMPLETED','FAILED')),
 confirmed_by varchar(100) NOT NULL,
 confirmed_at timestamptz NOT NULL,
 requested_by varchar(100) NOT NULL,
 requested_at timestamptz NOT NULL DEFAULT now(),
 decided_by varchar(100),
 decided_at timestamptz,
 decision_reason text,
 version bigint NOT NULL DEFAULT 1 CHECK(version > 0),
 correlation_id varchar(100) NOT NULL
);

CREATE INDEX bootstrap_remediation_customer_idx
 ON environment_management.bootstrap_remediation_requests(customer_id,status,requested_at DESC);

CREATE TABLE environment_management.bootstrap_remediation_history (
 history_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 request_id varchar(50) NOT NULL REFERENCES environment_management.bootstrap_remediation_requests,
 status varchar(30) NOT NULL,
 performed_by varchar(100) NOT NULL,
 performed_at timestamptz NOT NULL DEFAULT now(),
 details jsonb NOT NULL DEFAULT '{}',
 correlation_id varchar(100) NOT NULL
);

CREATE TRIGGER immutable BEFORE UPDATE OR DELETE
 ON environment_management.bootstrap_remediation_history
 FOR EACH ROW EXECUTE FUNCTION customer_management.reject_mutation();
