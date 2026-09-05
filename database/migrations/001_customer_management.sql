CREATE SCHEMA IF NOT EXISTS customer_management;
CREATE SCHEMA IF NOT EXISTS platform;

CREATE TABLE customer_management.customers (
 customer_id varchar(50) PRIMARY KEY,
 onboarding_request_id varchar(50) NOT NULL UNIQUE,
 name varchar(255) NOT NULL CHECK (length(btrim(name)) > 0),
 description text CHECK (length(description) <= 2000),
 status varchar(50) NOT NULL CHECK (status IN
 ('DRAFT','SUBMITTED','UNDER_REVIEW','APPROVED','REJECTED','ACTIVE','SUSPENDED','DEACTIVATED')),
 created_by varchar(100) NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 updated_by varchar(100), updated_at timestamptz,
 submitted_by varchar(100), submitted_at timestamptz,
 approved_by varchar(100), approved_at timestamptz,
 rejected_by varchar(100), rejected_at timestamptz, rejection_reason text,
 activated_by varchar(100), activated_at timestamptz,
 suspended_by varchar(100), suspended_at timestamptz, suspension_reason text,
 reactivated_by varchar(100), reactivated_at timestamptz,
 deactivated_by varchar(100), deactivated_at timestamptz, deactivation_reason text,
 review_cycle integer NOT NULL DEFAULT 0 CHECK (review_cycle >= 0),
 version bigint NOT NULL DEFAULT 1 CHECK (version > 0)
);
CREATE UNIQUE INDEX customers_live_name_uq ON customer_management.customers(lower(btrim(name)))
 WHERE status <> 'DEACTIVATED';
CREATE INDEX customers_status_created_idx ON customer_management.customers(status,created_at,customer_id);
CREATE INDEX customers_creator_idx ON customer_management.customers(created_by,customer_id);
CREATE TABLE customer_management.cloud_providers (
 provider_code varchar(50) PRIMARY KEY,
 provider_name varchar(100) NOT NULL,
 active boolean NOT NULL DEFAULT true,
 display_order integer NOT NULL DEFAULT 0
);
INSERT INTO customer_management.cloud_providers(provider_code,provider_name,display_order) VALUES
 ('AWS','Amazon Web Services',1),('AZURE','Microsoft Azure',2),
 ('GCP','Google Cloud Platform',3),('OCI','Oracle Cloud Infrastructure',4);
CREATE TABLE customer_management.customer_cloud_providers (
 customer_id varchar(50) NOT NULL REFERENCES customer_management.customers,
 provider_code varchar(50) NOT NULL REFERENCES customer_management.cloud_providers,
 created_by varchar(100) NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(customer_id,provider_code)
);
CREATE INDEX customer_provider_membership_idx ON customer_management.customer_cloud_providers(provider_code,customer_id);
CREATE TABLE customer_management.customer_contacts (
 contact_id varchar(50) PRIMARY KEY,
 customer_id varchar(50) NOT NULL REFERENCES customer_management.customers,
 contact_type varchar(50) NOT NULL CHECK (contact_type IN ('PRIMARY','TECHNICAL','BUSINESS','SECURITY','ESCALATION')),
 name varchar(255) NOT NULL, email varchar(255), phone varchar(50),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz
);
CREATE INDEX customer_contacts_customer_idx ON customer_management.customer_contacts(customer_id);
CREATE TABLE customer_management.customer_status_history (
 history_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 customer_id varchar(50) NOT NULL REFERENCES customer_management.customers,
 previous_status varchar(50), new_status varchar(50) NOT NULL,
 changed_by varchar(100) NOT NULL, changed_at timestamptz NOT NULL DEFAULT now(),
 reason text, comments text, correlation_id varchar(100)
);
CREATE INDEX customer_history_idx ON customer_management.customer_status_history(customer_id,history_id);
CREATE TABLE customer_management.customer_reviews (
 review_id varchar(50) PRIMARY KEY,
 customer_id varchar(50) NOT NULL REFERENCES customer_management.customers,
 review_cycle integer NOT NULL, reviewer_id varchar(100) NOT NULL,
 review_status varchar(50) NOT NULL CHECK (review_status IN ('UNDER_REVIEW','APPROVED','REJECTED')),
 comments text, rejection_reason text, reviewed_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(customer_id,review_cycle,review_status)
);
CREATE TABLE customer_management.customer_audit_log (
 audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 customer_id varchar(50) NOT NULL REFERENCES customer_management.customers,
 action varchar(100) NOT NULL, performed_by varchar(100) NOT NULL,
 performed_at timestamptz NOT NULL DEFAULT now(), source varchar(100) NOT NULL DEFAULT 'CUSTOMER_API',
 correlation_id varchar(100), old_value jsonb, new_value jsonb
);
CREATE INDEX customer_audit_idx ON customer_management.customer_audit_log(customer_id,audit_id);
CREATE TABLE platform.idempotency (
 actor_id varchar(100) NOT NULL, operation varchar(200) NOT NULL, key varchar(128) NOT NULL,
 request_hash char(64) NOT NULL, response jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(actor_id,operation,key)
);
CREATE TABLE platform.event_outbox (
 event_id uuid PRIMARY KEY, customer_id varchar(50) NOT NULL REFERENCES customer_management.customers,
 event_type varchar(100) NOT NULL, payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), published_at timestamptz,
 attempts integer NOT NULL DEFAULT 0, last_error varchar(100)
);
CREATE INDEX outbox_pending_idx ON platform.event_outbox(created_at) WHERE published_at IS NULL;
-- Audit/history/reviews remain immutable even if a future application accidentally issues an UPDATE.
CREATE FUNCTION customer_management.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Historical records are append-only'; END $$;
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON customer_management.customer_audit_log
 FOR EACH ROW EXECUTE FUNCTION customer_management.reject_mutation();
CREATE TRIGGER history_immutable BEFORE UPDATE OR DELETE ON customer_management.customer_status_history
 FOR EACH ROW EXECUTE FUNCTION customer_management.reject_mutation();
CREATE TRIGGER reviews_immutable BEFORE UPDATE OR DELETE ON customer_management.customer_reviews
 FOR EACH ROW EXECUTE FUNCTION customer_management.reject_mutation();
REVOKE ALL ON SCHEMA customer_management, platform FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA customer_management, platform FROM PUBLIC;
