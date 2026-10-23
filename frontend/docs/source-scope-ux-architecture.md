# Source-first migration UX architecture

Reviewed 23 October 2026. Frontend presentation and navigation only.

## Screen ownership

| Step | Screen                           | Responsibility and next action                                                                                                                                                                    |
| ---- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | Source connection                | Assessment identity, source registration, connector delivery and verification. Continue to discovery.                                                                                             |
| 2    | Source & Discover                | Read-only inventory and assessment views. Inspect namespace resources on demand; choose no execution or collection scope here. Continue to migration scope only with matching completed evidence. |
| 3a   | Migration scope / Choose scope   | Browse namespaces, explicitly select workloads, inspect observed dependencies and record the existing persistent-data strategy. Save scope.                                                       |
| 3b   | Migration scope / Files & images | Manage repository/registry access, explicitly analyze source evidence, inspect selected workloads, then create/collect/recover/export a private S3 workspace.                                     |
| 4    | Target & compatibility           | Select an active customer-owned supported target and assess the saved workload scope. Back returns to the same scope selection.                                                                   |
| 5–6  | Review & approval / Execute      | Review scope and target findings; return directly to Files & images. Existing package-validation, approval and execution limitations remain visible and enforced.                                 |

## Changes from the reviewed screenshots and code

1. Removed the deployment-evidence workbench from discovery. Opening discovery no longer triggers repository/image analysis or offers collection/recovery actions.
2. Removed discovery access controls. Repository/registry management belongs to Migration scope / Files & images; connector verification belongs to source connection during creation.
3. Moved collection to scope and removed its independent namespace picker. Collection is unavailable while scope is unsaved or changed. The existing API collects by namespace, so the UI explicitly says that collection can include artifacts beyond the individually selected execution workloads.
4. Show one matching workspace snapshot at a time; prefer a current inventory snapshot and allow explicit history selection. Other namespace scopes are not displayed as the active scope. Backend-reported stale snapshots retain their disabled recovery/export actions.
5. Replaced discovery's parallel Helm/deployment resolution paths with artifact-specific workspace actions: export a live definition, recover a Helm release, or review image access. Repository-candidate confirmation remains available inside selected workload evidence.
6. Kept source analysis visible ahead of workspace creation while workload details can stay collapsed. The existing analysis API scans configured sources; the evidence table filters its display to selected workloads. This is not described as a workload-scoped analysis API.
7. Used the existing shared PageHeading across discovery, scope, target and review. Removed conflicting discovery grid placement; retained theme/font tokens, neutral panels, green actions, local table scrolling and responsive stacking. Resource details are opened on demand.
8. Replaced raw target decision labels with readable text and clarified that an S3 export does not imply target readiness.

## Validation and limits

The local browser preview renders the actual React components against synthetic API fixtures, not a live AWS/customer session. Reviewed source connection, discovery inventory and findings, scope selection/save, files/images, target selection/results and review. Checked Back/Continue controls, disabled actions and workload selection. Source connection, discovery and scope were checked for page-wide horizontal overflow at 390, 768, 1024, 1280, 1440 and 1920px; none was observed. Vertical scrolling remains appropriate for long inventories, forms and artifact lists. Keyboard focus, modal behavior and error/permission gates also have focused component coverage; this is not a full accessibility conformance claim.

Focused tests cover discovery ownership/readiness, explicit discovery actions, scope saving/failure/read-only behavior, namespace/workload semantics, target gating, selected-source confirmation, visible analysis with collapsed details, workspace creation/collection/recovery/export, namespace filtering and snapshot history. TypeScript and the production frontend build are checked separately.

Live S3 writes, collectors, source-host recovery, registry access and target assessment must still be tested in DEV. No backend, authentication, migration selection rules, API payload contracts, infrastructure or feature gates were changed. The existing development/source-first route gate remains in place; the production legacy planner is not silently replaced.

## DEV acceptance steps

1. Pull the branch and restart the frontend development server. No Lambda deployment is needed for this UI change.
2. Open a completed source assessment. Confirm discovery contains Inventory and Assessment, with no namespace checkboxes, workspace creation, or duplicate Resolve actions.
3. Inspect namespace resources and assessment groups. Continue to scope; browse namespaces and explicitly select workloads.
4. Open Files & images before saving: collection must be blocked with a save-scope explanation. Save scope, then reopen Files & images.
5. Check repository/registry access and Analyze deployment sources. Inspect selected workload candidates; confirm a source if appropriate. Create a workspace and verify the displayed namespace boundary before starting collectors.
6. Exercise existing collection, missing-definition recovery, retained Helm recovery, image-access review and export against DEV. Verify stale snapshots remain blocked and other namespace scopes are not mixed in.
7. Change workload scope and confirm collection becomes unavailable until the scope is saved. Existing S3 workspaces must remain intact.
8. Save and continue to a target. Assess compatibility, open review, return to Files & images and back to scope. Approval/execution must not become available merely because files were saved to S3.

## Follow-up: post-creation navigation and bulk workload selection

Source connection is handled during migration creation. Discovery no longer repeats its workflow step or the connection-management disclosure. The post-creation workflow starts at Discovery & assessment (1) and has five visible stages. Existing backend identifiers, gates and saved planning payloads remain unchanged. Repository/registry management remains in Migration scope / Files & images.

Select all and Deselect all apply to the workload rows matching the namespaces currently being browsed and the search filter. Selections outside those results are retained. Bulk changes update the same local draft and dependency summary as individual selections; saving remains explicit. Empty-result, busy and read-only states disable the relevant bulk controls.

## Files & images preparation sequence

Files & images now has three local views: Check sources, Collect artifacts, Review & export. One persistent navigation toolbar contains Previous/Continue actions. The saved-scope footer is not duplicated below the artifact table. Source access and source-evidence controls appear only in Check sources; collection controls appear in Collect artifacts; export controls and the saved/excluded review appear in Review & export. Per-artifact recovery remains next to the affected item. Job attempts are collapsed into one expandable history summary.

Creation is blocked until workspace loading succeeds and while a current workspace already matches this assessment's saved namespace scope. The client handler also rejects duplicate creation attempts. A failed loading/creation request requires a successful refresh before another creation attempt. Older inventory snapshots retain their existing stale restrictions; a new namespace scope or inventory can still require a separate workspace.

S3 display uses returned storage metadata only. The current workspace-list API omits bucket/object keys. After the user creates an export, its existing response supplies the verified export bucket/key: the UI displays the export URI and its workspace folder above Saved / excluded. Exact per-artifact and historical receipt keys remain in the downloadable export manifest. If a response includes artifact storage metadata, the row displays that exact URI. No bucket names or per-artifact paths are guessed, and no export is created automatically merely to load a path. Displaying persisted per-object paths immediately on page load would require a separate backend read-response enhancement; that is outside this frontend-only change.

Component tests cover the three-view navigation, reuse of an existing workspace, explicit creation after a successful empty list response, creation disabling after success, exact returned S3 locations, export folder display and target navigation without another scope write.
