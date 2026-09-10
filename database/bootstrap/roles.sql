-- Run as database administrator AFTER migrations. NOLOGIN group roles contain no passwords.
-- Create LOGIN users separately, store credentials in Secrets Manager, and GRANT the relevant group.
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='navigan_api') THEN CREATE ROLE navigan_api NOLOGIN; END IF;
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='navigan_events') THEN CREATE ROLE navigan_events NOLOGIN; END IF;
END $$;
GRANT USAGE ON SCHEMA customer_management, platform TO navigan_api;
GRANT SELECT,INSERT,UPDATE ON customer_management.customers TO navigan_api;
GRANT SELECT ON customer_management.cloud_providers TO navigan_api;
-- FOR SHARE provider locks require UPDATE privilege on a column; application does not change it.
GRANT UPDATE(active) ON customer_management.cloud_providers TO navigan_api;
GRANT SELECT,INSERT,UPDATE,DELETE ON customer_management.customer_contacts,
 customer_management.customer_cloud_providers TO navigan_api;
GRANT SELECT,INSERT ON customer_management.customer_status_history,
 customer_management.customer_reviews,customer_management.customer_audit_log TO navigan_api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA customer_management TO navigan_api;
GRANT SELECT,INSERT ON platform.idempotency TO navigan_api;
GRANT INSERT ON platform.event_outbox TO navigan_api;
GRANT USAGE ON SCHEMA platform TO navigan_events;
GRANT SELECT ON platform.event_outbox TO navigan_events;
GRANT UPDATE(published_at,attempts,last_error) ON platform.event_outbox TO navigan_events;
-- Environment Management uses the same restricted application login and existing secret.
GRANT USAGE ON SCHEMA environment_management TO navigan_api;
GRANT SELECT ON environment_management.environment_types TO navigan_api;
GRANT SELECT,INSERT,UPDATE ON environment_management.environments TO navigan_api;
GRANT SELECT,INSERT ON environment_management.environment_versions,
 environment_management.environment_status_history, environment_management.environment_reviews,
 environment_management.environment_audit_log TO navigan_api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA environment_management TO navigan_api;
-- Cluster Management keeps request, Terraform execution and audit state in its own schema.
GRANT USAGE ON SCHEMA cluster_management TO navigan_api;
GRANT SELECT,INSERT,UPDATE ON cluster_management.clusters TO navigan_api;
GRANT SELECT,INSERT ON cluster_management.cluster_versions,
 cluster_management.cluster_status_history,cluster_management.cluster_audit_log TO navigan_api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA cluster_management TO navigan_api;
