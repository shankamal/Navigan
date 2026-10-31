# Fresh artifact collection for a workspace snapshot

Layout v2 creates a fresh collection for the selected migration scope. Each new inventory version gets its own workspace even if its content digest is unchanged. Files/images from an older workspace are not automatically reused. Existing workspace records retain their original saved paths.

New workspace paths are persisted when the index is created:

```text
navigan/customers/<customer-name>--<12-id-characters>/migrations/<migration-name>--<12-id-characters>/inventories/inventory-<version>--<utc>/workspaces/workspace--<full-workspace-uuid>/
```

| Artifact | Folder |
| --- | --- |
| Repository files | `repository-files/` |
| Container images | `container-images/` |
| Recovered source definitions and Helm data | `source-recovery/` |
| Export manifests | `exports/` |
| Review receipts | `reports/reviews/` |

Full customer/migration/source/inventory/workspace identities remain in the index. Display-name changes do not move existing objects. Workers, recovery, export and review operations all use the persisted workspace prefix. Checksums, pinned object versions, KMS encryption, source identity and customer authorization checks remain enforced.

The progress UI continues already-started recoveries through POLL, including a recovery belonging to another snapshot. A completed upload is validated and finalized into its original workspace, releasing the assessment's active recovery slot. A temporary status-check failure retries with backoff. Each workspace artifact has a separate limit of three recovery attempts; historical workspace attempts do not consume a new workspace's allowance. No new source recovery is started automatically.

## Staged rollout

1. Deploy the migration API code with `--workspace-layout-version 1`. This installs recovery/progress compatibility while keeping existing creation paths.
2. Update the workspace storage policy and rebuild/deploy the repository and image collectors from the same source. Existing database, network, source registrations and agent installations are retained.
3. Activate `--workspace-layout-version 2` on the API. The release checks both Lambda packages, the image's build-source fingerprint, runtime/network bindings and scoped storage permissions before allowing new paths. PROD checks the gate again when executing the prepared change set.
4. Deploy the progress UI update, then create a workspace from the saved scope and collect its artifacts. Verify artifact counts, exact S3 locations, checksums and export behavior. Deployment completion alone does not establish successful collection.

Use the existing PROD scoped prepare/execute helper and DEV migration-only helper. The user executes deployment and merge commands. Cleanup/reset commands are outside this release; old workspaces and artifacts remain retained.
