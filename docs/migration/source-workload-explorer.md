# Source workload explorer

The Source discovery screen now opens one workload explorer instead of four
separate evidence tabs. Namespace filtering and search change presentation only;
they never save migration scope or restrict connector discovery.

Select a namespace and workload to review deployment-definition candidates,
Helm release identity when detected, all regular/init container images, collected
dependency references, matching assessment findings and evidence notes. Jobs are
retained in a separate Job executions disclosure; no CronJob parent is guessed
from a name. Empty discovered namespaces remain selectable. Capture still covers
the collector's supported resource kinds; unsupported APIs and permissions are
not treated as complete evidence.

Assessment findings are linked by namespace/kind/name to the selected workload
and its collected dependencies. Cluster-wide or unlinked findings remain in
Source assessment findings. Multiple observations in an issue group remain
available. Repository mapping candidates and user confirmations do not verify
the deployed Git commit. A matching file is not inferred from an image name.

Source diagnostics opens a separate window for collection limits, the complete
repository index and compact expandable registry checks. The page no longer
places the complete file index below the selected workload.

## Refresh and analysis

Refresh discovery requests a new inventory/assessment through the existing API.
When the completed inventory appears, an authorized editor's discovery view
runs bounded, read-only repository/registry analysis once for that snapshot,
provided source connections are ready and inventory-only mode was not selected.
Recheck sources explicitly retries external source analysis without reinstalling
or replacing the source connector. A failed attempt is not retried in a loop.
Source analysis records its inventory digest; older/different-inventory analysis
is not presented as current. Legacy analysis without this binding is reanalyzed.
The backend also returns discovered namespaces and namespace-scoped dependency
objects with CAPTURED or NOT_OBSERVED status. Absence is not proof of deletion;
Secret/configuration values are not added to this response.

## Resolve actions and limits

A missing image opens the existing explicit artifact recovery panel. Registry
connection/authorization gaps open Manage connections instead. A validated
recovered image is labeled Cached copy recovered and offers View copy, while
the original registry status remains unchanged. Helm identity is
shown with original-package availability marked not checked; release metadata
alone does not verify a chart package. Helm release recovery remains separate
from container image recovery.

The existing recovery adapter checks the configured approved SSM host's
containerd cache only. It does not automatically inspect all nodes/runtimes.
Images require an evidence-backed digest and complete validated cached content.
Helm recovery is a partial retained release bundle, not a guaranteed original
chart archive. Source mappings without original files can be reviewed against
sanitized cluster snapshots; snapshots are not complete deployable manifests.
No automatic exports, image pushes or source workload changes are added here.

## Deploy and check

Use the existing DEV branch and deploy script. No new route, database migration
or connector upgrade is required by this change. If artifact recovery has not
been configured, use the existing `--enable-artifact-recovery` deployment option.

After deployment, open an assessment and select a namespace/workload. Check its
file/chart identity, every container, dependency evidence and linked findings.
Check an empty namespace, a registry-access gap and a missing-image Resolve path.
The UI should retain the selected context when a dialog is closed.
