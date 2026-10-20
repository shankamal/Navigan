# Source artifact resolution and deployment evidence

## User flow

Manage connections opens a separate window with Overview, Repository and
Registries sections. Existing credentials stay write-only; save/verify still
uses the existing scoped APIs. Unsaved edits must be saved or discarded before
closing. Setup is available through Manage connections before discovery.

Deployment structure uses a namespace/workload navigator and three evidence
sections: observed workload, container images, and deployment source. All
application and init containers remain accessible, including sidecars collected
as application containers; the UI does not guess sidecar roles from names.
Declared image references and digests are separate from observed Pod digests.
Long references expand and can be copied. Repository candidate matches are not
proof of the deployed Git revision. The artifact index groups each file once
and retains multi-document resources, scripts and workflow evidence.

Expand an image and choose Resolve image artifact, or use Resolve Helm release
artifact when a release identity was detected. Resolve opens a recovery panel;
it does not automatically export anything. The user explicitly chooses Check
cache and recover. The panel reports the attempt and offers a download only
after export and stored-object validation.

## First recovery adapter

- Existing approved AWS SSM delivery host only; no new connector node privileges,
  SSH fan-out, privileged Pods, registry pushes, image pulls or workload updates.
- Image recovery checks the configured host's local containerd `k8s.io` cache.
  A declared or observed SHA-256 digest is mandatory. A mutable tag alone is
  insufficient. Multiple observed digests require explicit selection.
- The exported OCI archive must contain the expected digest and every reachable
  manifest/config/layer blob, with matching sizes and SHA-256 hashes. Export is
  limited to 2 GiB and the host's Linux architecture. Missing layers, missing
  content, unsupported platforms or access failures never become success.
- Other source nodes and runtimes are not inspected. Kubernetes API-only and
  non-SSM sources report that recovery access is required. A running Pod does
  not guarantee exportable cached image content.
- Helm recovery reads deployed Helm release Secrets for the detected namespace
  and release. The latest retained deployed revision is exported as a compressed
  JSON release bundle containing chart data, values, manifest and hooks. This
  is **PARTIAL_RECOVERY**, not the original `.tgz`, signature verification,
  dependency-completeness verification or a ready-to-deploy chart. ConfigMap/SQL
  Helm storage backends, Git history and external artifact backups are not yet
  recovery adapters. Charts and referenced images require separate recovery.
- Helm bundles can contain sensitive values and Secret manifests. Contents never
  appear in status responses or command output. Only authorized migration editors
  for the customer can request recovery/download.

## Storage, API and boundaries

`POST /migrations/{migrationId}/deployment-evidence` accepts one `recovery`
action (`START`, `POLL`, `DOWNLOAD`) alongside the existing version. Refresh and
analysis continuation cannot be combined with recovery. Workloads and digest
identities must belong to the current discovered inventory. Customer scope,
source association and assessment version are checked before recovery.

Jobs are persisted in the source registration's existing JSON configuration,
keyed by migration. A source row lock prevents overlapping starts. At most one
attempt runs per assessment, with a maximum of 20 retained attempt records.
GET deployment evidence includes public job summaries; internal SSM handles,
storage keys and upload URLs are not exposed there. Status checks run every five
seconds only while the panel is open and an attempt is active. Reopening the
panel resumes the persisted attempt. Failed status checks require a retry.

Artifacts use private, encrypted S3 objects under
`customers/{customer}/migrations/{migration}/recovery/{job}/artifact`.
Recovery runs in two phases: export, then checksum-signed upload. Exports are
temporarily retained in a private job directory under
`/var/lib/navigan/source-recovery` on the configured host until polling resumes
and upload completes. At most two pending export directories are admitted per
host. Image exports reserve 1 GiB of free disk space. Completed uploads and
handled failures remove their local job files; interrupted host processes may
require operator cleanup of that specific job directory. No workload files are
removed. Upload URLs are stored only in a short-lived SSM SecureString, consumed/deleted
on the host; the API also attempts cleanup when an attempt terminates. Upload
URLs expire after 30 minutes. S3 verifies the upload checksum, the API verifies
size/checksum/encryption, and downloads use the validated object version.
Downloads expire after five minutes and re-check the stored object's integrity.
Active artifacts expire after 30 days, previous versions after seven days.

Source availability remains unchanged after recovery. `NOT_FOUND` describes the
queried registry endpoint, not proof of deletion. Authentication/authorization
failures and unreachable sources remain separate. The current metadata API does
not automatically prove original Helm chart package availability. Recovery is
not migration approval, target pull verification or target deployment.

## DEV deployment

Run from the existing `new_migration_approach_18oct26` checkout:

```bash
git pull --ff-only origin new_migration_approach_18oct26
python3 scripts/deploy-source-connection-screen-dev.py \
  --profile navigan --apply --enable-artifact-recovery
```

This updates the two DEV migration Lambda packages and deploys a separate private
recovery-storage CloudFormation stack. Its S3 policy attaches only to the existing
MigrationFunction role; it does not add source host/node permissions. The bucket
is retained if its stack is removed. No database migration, API route or connector
image upgrade is needed. An existing private bucket with equivalent scoped IAM
permissions can instead be supplied with `--recovery-artifact-bucket BUCKET`.
The recovery bucket environment variable is preserved by later DEV script runs.

The existing delivery role must allow SSM SendCommand/GetCommandInvocation and
the source-connector SecureString parameter path. The configured SSM host needs
AWS CLI, Python 3, kubectl/admin access for Helm recovery, and containerd `ctr`
access for image recovery, plus HTTPS access to S3. The feature reports access
failures; it does not silently expand these permissions.

No AWS deployment or live cache recovery was executed from the coding workspace.
Validate with a disposable missing artifact whose exact digest is known, inspect
its recovery result, download the archive, and independently verify it before
using it in subsequent migration planning. Do not delete a real image to test.
