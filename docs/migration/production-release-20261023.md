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

## 3. Scoped migration API preparation

Storage is now confirmed by user terminal output: both originally provisioned stacks are CREATE_COMPLETE. Use only workspace bucket `navigan-custmanagement-cfnstk-arti-workspacebucket-xc7zf8yedqxl`, owner `905418045935`, KMS key `arn:aws:kms:ap-south-1:905418045935:key/61119b9e-0d25-4459-9a2d-7e13dbb93568`. The extra bucket `navigan-custmanagement-cfnstk-sourc-recoverybucket-y0q8hr09sgsl` is left untouched. Private storage deployment record: `/mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-prod-migration-storage-2icl083o`.

Prepare without execution:

```bash
cd /mnt/b/Langchain_Ai/Navigan-migration-test
TMPDIR=/mnt/b/Langchain_Ai/navigan-deploy-tmp \
/mnt/b/Langchain_Ai/navigan-deploy-venv/bin/python \
  scripts/deploy-migration-api-prod.py --profile navigan --prepare
```

This requires only boto3 and pip in the existing deployment venv. The pinned Linux/CPython 3.12 PyYAML wheel is downloaded for the Lambda ZIP; it is not installed into the workstation Python. The script reads the live processed production templates, updates only the migration child template URL in the parent, preserves all existing parent parameters, and builds a scoped migration package from current source while retaining original dependencies. All migration module Python files and the shared GitHub App helper are updated in this API ZIP; the separate connector Lambda package is unchanged. Private rollback records include original ZIP, configuration and templates. Never publish these records or their environment values.

The API is bound only to the workspace bucket/KMS key. Any existing legacy recovery configuration is preserved, not created or repointed. New migration/source-setup/artifact routes inherit the actual production reference JWT authorizer, scopes and integration. Existing routes with unexpected protection are rejected, not overwritten. The dedicated discovery policy grants the API source-discovery role assumption and source-connection-secret operations; any configured GitHub App secret/key grants are restricted to their references. It does not change role trust or source-host permissions. Existing PROD GitHub App references may be read from ClusterFunction when absent on MigrationFunction; missing configuration is reported and must be supplied before repository collection.

The parent change set includes nested details. The validator permits only MigrationManagement at the root and MigrationFunction, the dedicated discovery policy, source-cluster invoke permission and explicitly listed protected migration routes in the child. Connector, unrelated role/trust, other application-stack, destructive or replacement changes stop execution. An API stage without automatic deployment stops readiness for a separately reviewed deployment plan. An unprocessed/non-JSON template also stops safely before package uploads rather than guessing at CloudFormation transforms.

Successful preparation prints the exact private `release-plan.json` path. It has NOT executed the deployment. Review the printed scope before running:

```bash
/mnt/b/Langchain_Ai/navigan-deploy-venv/bin/python \
  scripts/deploy-migration-api-prod.py --profile navigan \
  --execute /actual/path/from-preparation/release-plan.json
```

Use the actual printed path, not the placeholder above. Execution rechecks the AWS account, stack timestamp, Lambda revision/checksum and full change-set scope before applying. It verifies the new package digest and PROD workspace/source-first settings after completion. The collector services, frontend feature switch/immutable image promotion and authenticated workflow checks remain subsequent steps. Source-agent/connector compatibility still requires actual production workflow evidence before frontend acceptance.

Validation for preparation/execution boundaries: 76 focused mocked release tests passed (35 API, 26 storage and 15 migration tests). This does not establish live CloudFormation execution, backend integration acceptance or a completed production release.

## API dependency re-evaluation guard correction

The first live API preparation at `800f157` passed database/storage/API/JWT checks and found the existing PROD GitHub App configuration. It saved the rollback record under `/mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-prod-migration-api-hs_2r1sy` and created an unexecuted root change set, then stopped because CloudFormation also listed MigrationIntegration. No API or frontend update was executed. Preserve that record; do not execute that change set manually.

CloudFormation can mark resources referring to modified resources with Ref/GetAtt as dependency updates. The corrected guard reads both the current child template and the proposed child change-set template. It permits only full-definition-identical MigrationIntegration (AWS_PROXY), JWT routes referencing MigrationIntegration, or API Gateway invoke permissions referencing MigrationFunction, and only non-replacing Modify actions. Any changed property, route security/target difference, unrelated dependency, deletion or replacement remains rejected. Other resources, including the connector Lambda and role trust, remain outside scope. References: https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_ResourceChangeDetail.html and https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_GetTemplate.html.

Validation after correction: 92 focused release tests passed. Pull the correction and repeat `--prepare`; this creates a fresh checked plan and does not execute the release. The original backup and unexecuted change set are left untouched. API deployment, collectors and frontend promotion remain pending until actual successful output is supplied.

## API deployment confirmed / production collectors

User terminal output confirmed successful preparation and execution using `/mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-prod-migration-api-uyvrnt7c/release-plan.json`. The validated root change set was `navigan-prod-migration-api-9b194225c17642db/1096740c-2e2f-424d-9897-ad349214fdba`. Output verified the deployed API package and PROD configuration. Nine protected artifact routes, the scoped discovery policy and source invoke permission were added; MigrationIntegration was verified unchanged. Collector services, source agents and frontend were not updated by that operation. Keep the release directory and original rollback artifacts private.

Deploy the repository collector using the dedicated production entry point:

```bash
TMPDIR=/mnt/b/Langchain_Ai/navigan-deploy-tmp \
/mnt/b/Langchain_Ai/navigan-deploy-venv/bin/python \
  scripts/deploy-workspace-workers-prod.py \
  --profile navigan --repository --enable-schedule --apply
```

Stage the image collector with zero tasks:

```bash
TMPDIR=/mnt/b/Langchain_Ai/navigan-deploy-tmp \
/mnt/b/Langchain_Ai/navigan-deploy-venv/bin/python \
  scripts/deploy-workspace-workers-prod.py \
  --profile navigan --image --apply
```

The production wrapper explicitly binds the existing collector deployment mechanism to PROD database `navigan`, parent `navigan-custmanagement-cfnstk` and ECR repository `navigan/prod-workspace-image-collector`. It re-verifies actual API function identity/revision/role, source-first flag, schema/grants and workspace bucket/KMS settings. Local collector/source edits stop the release without discarding files. The reusable helper retains its DEV defaults for existing commands and tests. Separate stacks are `navigan-custmanagement-cfnstk-workspace-repositories`, `navigan-custmanagement-cfnstk-workspace-image-runtime` and `navigan-custmanagement-cfnstk-workspace-images`; neither API nor source connector is updated. Registry trust and private network access must be verified before starting image tasks. No source-role trust is changed automatically. A supplied `--worker-image` must be an immutable digest from the dedicated PROD collector repository; do not pass a DEV image. Docker pushes are bounded at ten minutes; an interrupted local image remains available to finish its push and resume with a digest.

The image service is intentionally staged at DesiredCount=0. Capture its worker role ARN, image digest, service name and runtime cluster outputs before configuring exact registry role authorization and starting it. The repository schedule can be enabled by the explicit flag above. Actual collection readiness and authenticated workflow acceptance are still pending.

## Frontend production feature switch prepared

The four migration server routes now use a shared runtime switch. Explicit `MIGRATION_SOURCE_FIRST_ENABLED=true` enables the source-first screens in production; unset/false keeps the legacy flow. Existing DEV default behavior is retained. Next.js `connection()` ensures the switch is evaluated per request rather than frozen during the image build. Production NODE_ENV and all authentication/preview permission checks remain unchanged. The future frontend task needs this explicit server environment setting; no ECS task has been changed by the source commit.

Validation: 117 focused Python tests (existing release guards and DEV/PROD collector tests), 28 frontend feature-switch/proxy tests, TypeScript and production build passed. The build marks all four migration routes dynamic. No claim of live collector deployment, authenticated production acceptance or frontend rollout follows from these checks. Frontend remains on the last observed task revision :8 until the separate immutable image release.

## Single-bucket correction

The user clarified that DEV used one workspace bucket. Current artifact_recovery.py confirms that requests bound to a workspace use storage_configuration() from artifact_workspace.py and save recovered objects into the workspace bucket with its KMS key. MIGRATION_RECOVERY_BUCKET is only the older recovery path without a workspace binding. An earlier production-script revision unnecessarily provisioned both templates; the corrected script provisions only the workspace stack. No existing bucket is deleted or repurposed.

User terminal output now confirms migrations 027/028 and scoped grants committed successfully to navigan. Storage deployment is still awaiting confirmed output; the earlier storage attempt stopped at the missing-table preflight before provisioning any resources. Validation of the single-bucket script: 41 focused tests passed, including exact one-stack provisioning and rejection of the legacy recovery stack.
