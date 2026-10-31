# Clean artifact collection preparation

The reset scope is all migration assessments in both DEV and PROD. Preserve customer records, assessments, captured inventories and saved scopes. Clear artifact workspace state only through a reviewed reset after old collectors have been quiesced.

Run `scripts/prepare-migration-artifact-reset.py --profile <profile>` to prepare a private local inventory and a compact summary. This command only reads AWS and database metadata. It does not delete objects, object versions, jobs or database rows, and it does not stop/start services.

The inventory resolves both deployed migration APIs, verifies their account/database/workspace ownership, checks current Aurora/proxy health, records assessment identities and scope fingerprints, and counts workspace/job state. It inventories exact old workspace/recovery object versions, delete markers and incomplete uploads for assessments verified in the corresponding databases. Other key patterns and unknown assessment identities are preserved for review. Shared buckets are scanned once using only verified assessment identities.

Proposed new roots use `navigan/customers/<name>--<12-id-characters>/migrations/<name>--<12-id-characters>/`. Each inventory and workspace has its own child directory. Artifact categories are `repository-files`, `container-images`, `source-recovery`, `exports` and `reports`. Full identities remain in metadata; final workspace paths use the full unique workspace UUID. Generated prefixes must be persisted so renaming a customer or assessment does not relocate its objects.

Preparation does not deploy the proposed layout. Deletion is not enabled by this command. Current database/collector access must work, active jobs must be reconciled and writers paused, the new layout and its scoped S3 permissions must be deployed, and the exact reset inventory must be reviewed before execution. A final reset must invalidate old job/export references as well as removing S3 versions; deleting visible folders alone would leave broken database references and retained versioned bytes.
