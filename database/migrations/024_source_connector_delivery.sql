BEGIN;

ALTER TABLE migration_management.source_clusters
  ADD COLUMN delivery_method varchar(30) NOT NULL
    DEFAULT 'MANUAL_HELM'
    CHECK(delivery_method IN (
      'MANUAL_HELM',
      'AWS_SSM',
      'GITOPS'
    )),
  ADD COLUMN delivery_configuration jsonb NOT NULL DEFAULT '{}';

ALTER TABLE migration_management.source_clusters
  ADD CONSTRAINT source_cluster_delivery_configuration_object
  CHECK(jsonb_typeof(delivery_configuration) = 'object');

COMMIT;
