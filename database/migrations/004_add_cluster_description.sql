ALTER TABLE cluster_management.clusters
ADD COLUMN IF NOT EXISTS description text;
