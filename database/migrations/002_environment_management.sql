CREATE SCHEMA environment_management;
CREATE TABLE environment_management.environment_types (
 code varchar(50) PRIMARY KEY, active boolean NOT NULL DEFAULT true, display_order integer NOT NULL DEFAULT 0
);
INSERT INTO environment_management.environment_types(code,display_order)
 SELECT code, ord FROM unnest(ARRAY['DEV','TEST','QA','SIT','UAT','PT','PERFORMANCE','PREPROD','PROD','DR','SANDBOX','OTHER']) WITH ORDINALITY AS t(code,ord);
CREATE TABLE environment_management.environments (
 environment_id varchar(50) PRIMARY KEY,
 customer_id varchar(50) NOT NULL REFERENCES customer_management.customers,
 provider_code varchar(50) NOT NULL,
 kubernetes_distribution varchar(20) NOT NULL,
 environment_name varchar(150) NOT NULL CHECK(length(btrim(environment_name))>0),
 environment_type varchar(50) NOT NULL REFERENCES environment_management.environment_types,
 description varchar(4000) NOT NULL DEFAULT '',
 status varchar(50) NOT NULL CHECK(status IN ('DRAFT','SUBMITTED','UNDER_REVIEW','APPROVED','REJECTED','ACTIVE','SUSPENDED','DEACTIVATED')),
 configuration_schema_version varchar(20) NOT NULL,
 configuration jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(configuration)='object'),
 version bigint NOT NULL DEFAULT 1 CHECK(version>0), approved_version bigint,
 created_by varchar(100) NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 updated_by varchar(100), updated_at timestamptz,
 workflow jsonb NOT NULL DEFAULT '{}',
 FOREIGN KEY(customer_id,provider_code) REFERENCES customer_management.customer_cloud_providers(customer_id,provider_code),
 CHECK((provider_code,kubernetes_distribution) IN (('AWS','EKS'),('AZURE','AKS'),('GCP','GKE'),('OCI','OKE')))
);
CREATE UNIQUE INDEX environment_name_unique ON environment_management.environments(customer_id,provider_code,lower(btrim(environment_name)));
CREATE INDEX environment_filter_idx ON environment_management.environments(customer_id,status,created_at,environment_id);
CREATE INDEX environment_provider_idx ON environment_management.environments(provider_code,environment_type);
CREATE INDEX environment_region_idx ON environment_management.environments((configuration #>> '{location,region}'));
CREATE TABLE environment_management.environment_versions (
 environment_id varchar(50) NOT NULL REFERENCES environment_management.environments,
 version bigint NOT NULL, snapshot jsonb NOT NULL, created_by varchar(100) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), change_reason text,
 PRIMARY KEY(environment_id,version)
);
CREATE TABLE environment_management.environment_status_history (
 history_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 environment_id varchar(50) NOT NULL REFERENCES environment_management.environments,
 previous_status varchar(50), new_status varchar(50) NOT NULL,
 changed_by varchar(100) NOT NULL, changed_at timestamptz NOT NULL DEFAULT now(),
 reason text, comments text, correlation_id varchar(100)
);
CREATE TABLE environment_management.environment_reviews (
 review_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 environment_id varchar(50) NOT NULL REFERENCES environment_management.environments,
 environment_version bigint NOT NULL, reviewer_id varchar(100) NOT NULL,
 review_status varchar(50) NOT NULL, reason_code varchar(100), reason text, comments text,
 reviewed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE environment_management.environment_audit_log (
 audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 environment_id varchar(50) NOT NULL REFERENCES environment_management.environments,
 action varchar(100) NOT NULL, performed_by varchar(100) NOT NULL,
 performed_at timestamptz NOT NULL DEFAULT now(), correlation_id varchar(100), old_value jsonb, new_value jsonb
);
CREATE INDEX environment_history_idx ON environment_management.environment_status_history(environment_id,history_id);
CREATE INDEX environment_reviews_idx ON environment_management.environment_reviews(environment_id,review_id);
CREATE INDEX environment_audit_idx ON environment_management.environment_audit_log(environment_id,audit_id);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['environment_versions','environment_status_history','environment_reviews','environment_audit_log'] LOOP
 EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON environment_management.%I FOR EACH ROW EXECUTE FUNCTION customer_management.reject_mutation()',t);
 END LOOP;
END $$;
REVOKE ALL ON SCHEMA environment_management FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA environment_management FROM PUBLIC;
