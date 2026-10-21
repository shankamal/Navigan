# Migration artifact workspace — primary implementation goal

Continue this work before unrelated UI redesigns or other features.

## Checkpoint

Phase 1 is implemented: private KMS/S3 template, snapshot-bound workspace indices,
metadata tables, authorized create/read/list API, namespace selection UI and DEV packaging.
It stores ONLY the index, not repository files or image archives. No AWS or database
changes have been applied by the agent. Browser visual validation is pending.

Remaining phases, in order:
1. Durable collection jobs and leases, then immutable repository downloads including supporting files and Helm/Kustomize dependencies.
2. Digest-addressed image archives with required platforms, multipart upload and content validation through a long-running worker.
3. Integrate existing cache/Helm recovery; add live configuration exports and customer artifact upload where recovery is unavailable.
4. Per-artifact progress, retry/resolve, authorized downloads and collected/validated states.
5. Approved target registry publication and separately versioned target definitions/preflight.

Do not mark collected artifacts validated until the respective integrity and content checks pass. Do not upgrade candidate repository matches on download. Persistent data migration and traffic switching remain separate workstreams.

## API

- POST /api/v1/migrations/{migrationId}/artifact-workspaces
- GET /api/v1/migrations/{migrationId}/artifact-workspaces (latest 50)
- GET /api/v1/migrations/{migrationId}/artifact-workspaces/{workspaceId}

POST requires migration.edit, customer authorization, Content-Type application/json,
Idempotency-Key and body: {"version":2,"inventoryDigest":"<current digest>","namespaces":["shop"]}.
Read operations require migration.view and customer authorization. Stale inventory,
unknown namespaces and changed migration versions are rejected. An older workspace
is marked stale when its source or inventory changes.

S3 prefix: customers/{customerId}/migrations/{migrationId}/workspaces/{workspaceId}/.
The immutable workspace ID identifies its snapshot; inventory digest/version is in
the manifest. Repository candidate confidence remains in workload mapping evidence.
Missing definitions stay EXPORT_REQUIRED. Tag-only images stay DIGEST_REQUIRED.
Access failures remain distinct from missing images. Shared references are deduplicated
within a workspace; cross-workspace deduplication is a later worker concern.

## Deploy foundation in DEV

1. Back up the DEV database. Apply 027_migration_artifact_workspaces.sql through the existing migration-owner process (scripts/migrate.py uses MIGRATION_DATABASE_URL, supplied securely). Do not change already applied migrations.
2. Apply the new workspace table grants in database/bootstrap/roles.sql for navigan_api. No DELETE rights are added.
3. From new_migration_approach_18oct26 run:

   python3 scripts/deploy-source-connection-screen-dev.py --profile navigan --apply --enable-artifact-workspace

This provisions dedicated storage, configures Lambda and adds JWT routes; it does
NOT apply SQL. Existing recovery storage and source-node permissions are unchanged.
Do not combine the workspace flag with --finish-deployment.

For regular IaC deployment, deploy workspace-storage.yaml with MigrationFunctionRoleName
and pass WorkspaceBucketName, WorkspaceKmsKeyArn and WorkspaceBucketOwner outputs to
the migration-management stack. Parent-stack parameter plumbing may be needed;
the DEV script configures these directly.

Refresh the frontend, expand Artifact workspace, select namespaces, and create an
index. Verify PLANNED, zero collected artifacts and a versioned KMS-encrypted S3 object.
Verify source refresh marks the previous workspace stale and another customer cannot
read it. Live AWS/DB smoke tests and browser review remain required.

## Security and failure boundaries

Storage blocks public access, enforces TLS and the dedicated KMS key, enables versioning,
and retains objects on stack deletion. There is no automatic artifact expiry yet;
retention must respect active migrations. Incomplete multipart uploads expire in one day.

A conditional manifest PUT supplies SHA-256 and the expected bucket owner, then verifies
the stored version, checksum, length and encryption before inserting database records.
A later database rollback may leave an unreferenced object: add an orphan reconciler
before large-scale operation, and never delete referenced or active versions.

Only allowlisted provenance enters the public index. Raw Secrets, Helm values, file
contents and credentials must remain behind a separate authorized content access flow.
The planned inventory does not yet enumerate complete dependencies. Dependency expansion
and cluster-scoped prerequisite handling belong in the collection phase.

Next implementation task: durable collection job state machine and dispatch/outbox,
then immutable repository collection. Persist intent before dispatch, use leases,
idempotent retries and versioned output verification. Image bytes must bypass API Gateway.


## Phase 2 checkpoint — repository collection

Implemented a transactional PostgreSQL job queue, bounded immutable GitHub file
bundles, and a scheduled worker. POST collection-jobs enqueues only repository
definitions. Existing successful artifacts are not downloaded again. Explicit retry
requeues failed jobs. Crashed jobs can be reclaimed after five minutes, up to three
attempts; an expired worker cannot publish results. No credentials or upstream error
bodies enter public job records. Current source association, snapshot, customer and
repository authorization configuration are checked before downloading and before
publishing a result.

Repository files are fetched at a 40-character commit SHA, and every Git blob is
hash/size verified. HELM/KUSTOMIZE candidates collect bounded local sibling content.
Symlinks/submodules, truncated trees, missing files and size/time limits fail with
explicit codes. Maximum: 50 files, 1 MB each, 5 MB total, 120-second fetch budget.
File contents are stored as base64 in a private JSON bundle, not exposed by the list
API. The bundle's S3 version and checksum are verified before marking COLLECTED.
It is not a rendered or deployment-ready package: external chart dependencies,
Kustomize remote bases, deploy-time values and dependency completeness need review.
Image and live-resource recovery adapters remain pending integration.

The initial S3 workspace-manifest.json is immutable planning evidence. PostgreSQL
tracks current artifact/job state. A versioned final workspace export is still needed
when all collection adapters are complete. S3 objects orphaned by lost leases/DB
failures remain subject to the planned reconciler.

### Deploy this increment

Apply database migration 028 after 027 and the new table grants in roles.sql before
updating the API. The DEV API script includes the worker modules and collection route,
but DOES NOT provision its scheduled Lambda.

Provision WorkspaceCollectorFunction from the migration-management SAM template with
EnableWorkspaceCollector=true and the existing WorkspaceBucketName, WorkspaceKmsKeyArn,
and WorkspaceBucketOwner. It polls one job per minute, has a 240-second timeout and
reuses the migration runtime role/DB identity. Source credential access is inherited
from that role. Parent stack parameters must pass these values through when deploying
a nested stack. Supply WorkspaceGithubAppId and WorkspaceGithubKeySecretArn for GitHub
App authentication; the optional key policy grants read access to that exact secret.
Its encryption key must also be decryptable by the runtime. Token/public connections
use the existing source authentication configuration. Ensure VPC egress to GitHub,
S3, Secrets Manager and KMS. Enable the worker only after SQL/grants/storage are ready.

For a controlled DEV smoke test with the same secured DB/AWS environment, run:
`PYTHONPATH=src python -m navigan.modules.migration_management.workspace_worker`.
It claims at most one queued repository job, prints only a sanitized outcome and exits.
Do not run with production credentials to test a DEV workspace.

In the UI: load workspaces, click Collect / retry repository files, then Refresh
workspaces to inspect progress. No browser transfer is used. Refresh is manual in
this increment. Verify that a candidate stays unconfirmed, an image remains pending,
and the workspace stays PARTIAL after successful repository collection.

Next: image archive collection and complete dependency resolution; recovery linkage
and authorized artifact downloads. Keep this as the primary implementation goal.
