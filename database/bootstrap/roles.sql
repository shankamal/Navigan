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
