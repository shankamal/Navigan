# Production migration release — 23 October 2026

The user requested promotion of the current frontend and migration backend. Use the existing WSL checkout and branch `new_migration_approach_18oct26`. Preserve unrelated local files; do not reset, clean or create another worktree.

## Verified starting point

- Account `905418045935`, region `ap-south-1`, profile `navigan`.
- PROD parent `navigan-custmanagement-cfnstk`, database `navigan`.
- Migration nested stack `navigan-custmanagement-cfnstk-MigrationManagement-15LMVISK00HR5`, UPDATE_COMPLETE.
- Frontend cluster `navigan-frontend-Cluster-bw32Pkwxn8Cs`, service `navigan-frontend-Service-vMtHq9h7A9mz`.
- Frontend rollback target `navigan-frontend-TaskDefinition-j9W80aX9PBkf:8`, desired/running 1/1, rollout COMPLETED in user-supplied output.
- Read-only SQL initially found source_clusters present and all three workspace tables absent. The first migration attempt stopped at the DEV-only guard before any AWS calls. Runner correction `cb7c538` permits scoped PROD migrations only with exact `--confirm-production-database navigan` confirmation.
- User subsequently replied “done”; the storage preflight independently checks the table and runtime-grant state rather than assuming a successful DB commit.

## 1. Workspace schema

Use `scripts/migrate_data_api.py --workspace-only --database navigan --confirm-production-database navigan` with the verified PROD cluster/secret references. Validate with `--dry-run` first. Only migrations 027/028 and their scoped grants are selected. Earlier migrations 025/026 are historical completed work; do not rerun the full migration directory as a release ritual.

## 2. Dedicated PROD storage

Read-only check, using the existing deployment venv:

```bash
cd /mnt/b/Langchain_Ai/Navigan-migration-test
/mnt/b/Langchain_Ai/navigan-deploy-venv/bin/python \
  scripts/deploy-migration-storage-prod.py --profile navigan
```

Provision storage:

```bash
TMPDIR=/mnt/b/Langchain_Ai/navigan-deploy-tmp \
/mnt/b/Langchain_Ai/navigan-deploy-venv/bin/python \
  scripts/deploy-migration-storage-prod.py --profile navigan --apply
```

The script creates only `navigan-custmanagement-cfnstk-artifact-workspace`, containing one private S3 bucket and its KMS key, using the existing reviewed workspace template and actual production MigrationFunction execution role. It prepares a scoped change set, rejects unrelated resources/removal/import/replacement, then executes. New IAM resources are inline storage policies attached to the existing API role; no role trust, source-host access or authentication changes are made. The workspace bucket uses KMS encryption, versioning, private ownership and full public-access blocking. Workspace-bound live-definition and Helm recovery use this same bucket. The separate legacy recovery-storage path is not provisioned by this release. Retained storage resources are not deleted on stack rollback/deletion.

The script verifies all three PROD workspace tables and every SELECT/INSERT/UPDATE grant before provisioning. It checks the API revision again before execution. Existing stacks must have the same role parameter; repeated unchanged deployments are handled without executing empty change sets. Deployment records use a private directory under TMPDIR and contain no secret values or signed URLs.

Success prints `PROD migration storage deployed and verified. API configuration/code and frontend are unchanged.` Keep the bucket/KMS-key outputs and deployment-record directory for the next phase. If the storage stack fails, inspect its events and resume; do not delete buckets or source data.

## Remaining release phases — not completed by the storage script

1. Prepare the scoped migration API package/routes/policies/configuration using the current production configuration and reviewed change set. Preserve unrelated nested stacks and source agents. Bind the verified PROD storage outputs; do not reuse DEV bucket/database settings.
2. Provision PROD repository/image collectors with appropriate private networking, database grants and exact registry-role authorization. Validate any required trust additions without removing existing principals or ExternalId conditions. DEV worker deployment scripts deliberately target DEV and must not be run against PROD.
3. Replace the frontend's development-only migration route gates with a proper production feature switch. Preserve real authorization and production NODE_ENV; do not enable UI-preview permission bypasses.
4. Build the exact release frontend with verified production OIDC public configuration; push a unique immutable ECR tag and resolve its digest. Copy the current production task definition, changing only the image and any explicitly required, reviewed feature-switch setting. Update only the Navigan frontend service.
5. Confirm actual running task/image digest, steady state, login/callback, read-only platform navigation and the migration API/UI workflow. ECS health alone is insufficient. Keep task `:8` as the known baseline; capture the actual current task again immediately before switching.

Storage completion is not API deployment, collector readiness, frontend rollout, target workload migration or traffic cutover. The agent has no AWS credentials/CLI/Docker in its sandbox; all live release operations are executed by the user in WSL, with outputs recorded as evidence.

## Single-bucket correction

The user clarified that DEV used one workspace bucket. Current artifact_recovery.py confirms that requests bound to a workspace use storage_configuration() from artifact_workspace.py and save recovered objects into the workspace bucket with its KMS key. MIGRATION_RECOVERY_BUCKET is only the older recovery path without a workspace binding. An earlier production-script revision unnecessarily provisioned both templates; the corrected script provisions only the workspace stack. No existing bucket is deleted or repurposed.

User terminal output now confirms migrations 027/028 and scoped grants committed successfully to navigan. Storage deployment is still awaiting confirmed output; the earlier storage attempt stopped at the missing-table preflight before provisioning any resources. Validation of the single-bucket script: 41 focused tests passed, including exact one-stack provisioning and rejection of the legacy recovery stack.
