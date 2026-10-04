-- A GitHub App has one installation per organization, while Navigan
-- stores customer-scoped authorization records. Multiple authorized
-- customers may therefore reference the same installation.

ALTER TABLE cluster_management.github_app_connections
DROP CONSTRAINT IF EXISTS
github_app_connections_installation_id_key;

CREATE INDEX IF NOT EXISTS github_connections_installation_idx
ON cluster_management.github_app_connections(installation_id)
WHERE installation_id IS NOT NULL;
