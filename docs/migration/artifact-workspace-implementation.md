# Migration artifact workspace — primary implementation goal

Continue this work before unrelated UI redesigns or other features.

## Checkpoint

| Increment | Code status | Live status |
|---|---|---|
| Workspace index, private storage, API and UI | Implemented | Not deployed/verified here |
| Durable queue and repository collection | Implemented | Not deployed/verified here |
| Digest-pinned available image collection | Implemented; see image checkpoint | Container build and real transfer not performed here |
| Missing-artifact recovery integration | Next | Pending |
| Final export/download and complete dependencies | Pending | Pending |
| Target registry publishing and target preflight | Pending | Pending |

The initial index does not copy artifacts. Collection jobs perform repository and
available-image transfers using their respective workers. No live AWS, registry or
DB mutations were performed here. Collected is distinct from full migration validation.
Persistent data migration and traffic switching remain separate workstreams.

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


## Available-image collection checkpoint

The collection-jobs POST now accepts artifactKind=IMAGE; its default remains
REPOSITORY_DEFINITION. Only IMAGE artifacts in PENDING_COLLECTION are queued.
Missing images, unresolved digests and access-required records remain unresolved.
Both workers filter job claims by kind. The image worker renews a five-minute lease
every 20 seconds; expired or lost leases cannot publish results. Source/customer,
snapshot, registry configuration and credential metadata are rechecked before acceptance.

The dedicated container runs skopeo copy --all --preserve-digests against an explicit
digest with TLS verification. It never executes an image, switches a tag, publishes
to a target registry or changes source permissions. Each archive blob is hashed; the
reachable manifest/config/layer graph, descriptor sizes, source digest and available
OS/architecture platforms are checked. A pinned index copies its descendants; a pinned
platform manifest preserves that platform, not every platform of the original tag.
Target compatibility and image signature/provenance trust remain separate checks.

Images upload directly from worker disk to S3 in 16 MiB parts. Part SHA-256 values,
the stored composite checksum, length, KMS encryption and object version are checked.
A separate full-file SHA-256 is stored in artifact metadata. Incomplete failed uploads
are aborted; bucket lifecycle is a fallback. Completed but unreferenced objects still
need the planned reconciler. Current limits: 10 GiB archive, 30-minute transfer,
bounded file count, metadata memory and descriptor nesting. Image transfer does not
run inside the 240-second repository Lambda.

Authentication supports public registries, saved username/token mode and approved
AWS_ROLE/AWS_EXISTING_ROLE ECR connections. BEARER mode reports
REGISTRY_AUTH_MODE_UNSUPPORTED; credentials are not placed in argv or logs. Copy uses
a temporary 0600 auth file removed afterward. Generic IMAGE_PULL_FAILED must not be
interpreted as deletion: recheck source access/evidence before cache recovery.

### Build and deploy

No additional migration beyond 027/028 is required. Deploy updated API AND repository
worker code so claims separate artifact kinds. Apply the updated workspace storage
policy for AbortMultipartUpload. The DEV API script packages these modules but does
not provision the image worker service.

From repository root:
`docker build --platform linux/amd64 -f workspace_image_worker/Dockerfile -t <approved-repository>:<version> .`

Build/push through the approved DEV pipeline, obtain the immutable digest, and provide
it as WorkerImage to image-collector-service.yaml. Docker/skopeo were unavailable in
the agent runtime, so building and a real transfer remain rollout gates. The build
downloads the official RDS CA bundle for TLS verification.

The Fargate template requires an existing ECS cluster, execution role (ECR pull/logs),
private subnets/security groups, database proxy/secret settings, workspace bucket
owner/KMS key, and optional exact ECR source-role ARNs separated by commas. It creates
a separate task role/service. DesiredCount defaults to zero; configure and verify
before setting it to one. Worker tasks use 30 GiB ephemeral storage and a read-only
root filesystem. The entrypoint initializes the temporary mount then drops to UID/GID
10001 before importing worker code. Allow DB connectivity from its security group
and egress to source registry/blob endpoints, Secrets Manager, S3 and KMS. No public
IP is assigned. The template uses Linux/x86_64; copied images can be other architectures.

For cross-account ECR, the source role must explicitly trust WorkerTaskRoleArn using
the saved External ID. Grant GetAuthorizationToken and the required repository reads:
DescribeImages, BatchGetImage, GetDownloadUrlForLayer, BatchCheckLayerAvailability.
The assumed pull session narrows repository actions to the requested repository.
Existing metadata-only discovery sessions stay unchanged. The implementation does
not modify source role trust or permissions.

After deployment: load a current workspace, click Collect / retry available images,
refresh job state and verify the versioned archive and reported actual platforms.
Missing images must remain RECOVERY_REQUIRED. Test interrupted transfer/retry and an
incomplete image before wider use. Repository mapping confidence must remain unchanged.

Next primary task: link cache/Helm/live-definition recovery to workspace artifacts,
then authorized content downloads and final workspace export. Target publishing is
still a later separate action.
