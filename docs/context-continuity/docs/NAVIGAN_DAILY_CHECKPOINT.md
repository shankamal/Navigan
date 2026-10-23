## Current requirement and PROD delivery trust — 23 October 2026

User clarified: an authorized customer should register an association with the same existing healthy physical source connector in the SAME Navigan instance, without another agent installation per customer. The prior source-scoped installation change prevents resource collisions but is NOT the required shared-connector association implementation. Do not present it as the final lifecycle solution or require retirement/reassignment of JPMC records. Keep customer-scoped permissions, explicit authorization of additional customer bindings, assessment/artifact isolation and association revocation. Source agent tokens must not be copied between customer records. DEV connectivity alone does not prove PROD connectivity; the agent's actual API endpoint/connector ID must be checked first.

User successfully executed the scoped API plan /mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-prod-migration-api-_efn9ga1/release-plan.json for code 064a72a058aa4a1d01006340ec69863505f188f1. MigrationFunction updated; MigrationIntegration unchanged dependency verified. Frontend remains :9; later UI changes are not deployed. Subsequent Install connector failed before SSM submission: CloudWatch correlation 052c7188-be32-45bd-a9d2-aed2ec8341f0 and e803245c-f2e1-4f56-947f-1fb06e161997 reported AccessDenied at source_connector_installation.py:309 (STS AssumeRole). This is not a database failure despite transaction-wrapper logging.

Live user diagnostic established identity-policy sts:AssumeRole evaluation allowed for PROD MigrationFunctionRole-kPeJA6r1VbOE with no missing context. NaviganSourceConnectorDeliveryRole trusted only DEV MigrationFunctionRole-zfZY0tTybea6. User then added exact PROD principal via Sid NaviganProductionSourceDelivery, preserving existing DEV statement and requiring sts:ExternalId matching SRC-*. Output confirmed update and verification. Private original trust backup: /mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-delivery-trust-v54qebuc/original-trust.json. No connector installation, customer reassignment or assessment cancellation was performed by that IAM update.

Next: read-only SSM inspection of source host i-08e28d9b2242cbd53 using /etc/kubernetes/admin.conf, namespace navigan-migration. Print only deployment identity/readiness and public NAVIGAN_API_BASE_URL/NAVIGAN_SOURCE_CONNECTOR_ID; never connector tokens, secrets or complete environment data. Compare with configured PROD connector API endpoint. Then implement the explicit shared-connector customer binding flow through APIs/connector assignment/report authorization. Generic AWS access failures also need clear client-safe errors. Do not blindly repeat Install connector simply to associate another customer. Original goal remains testing the DEV-validated migration/discovery/scope/artifact collection/export workflow end to end in PROD. Live functionality remains unverified.

---

## Source connector lifecycle fix (pending PROD rollout) — 23 October 2026

User explicitly clarified the goal: existing/new source connections must work for every authorized customer and existing/new assessments, so the DEV migration workflow can be tested in PROD. Db Schenker is the current test customer and owns the intended target. Do NOT treat this as authorization to retire/reassign the JPMC source or cancel corebanking. Earlier ownership-transfer suggestions were an incorrect direction.

Root cause found in source_connector_installation.py: every registration installed the same Deployment, credentials Secret, image pull Secret, ServiceAccount, ClusterRole/Binding and pod selector in navigan-migration. The host-wide conflict guard therefore blocked Db Schenker because of another customer's legacy draft, despite both registrations lacking current heartbeats.

Fix: AWS SSM installations now use deterministic navigan-source-<full registration UUID> resource names for deployment/secrets/service account/RBAC/selectors/rollout. The shared namespace is retained; legacy/shared deployments and other registrations are never replaced or deleted. Enrollment revocation remains scoped to that source_cluster_id. Backend preflight checks edit/customer access, revocation, delivery configuration and fresh heartbeat; other registrations no longer block isolated resources or leak their metadata. A healthy current connector is reused, not rotated. Recovery accepts a DRAFT linked to the same customer/source as well as existing pending states; association/version checks remain enforced.

Registration requests for the same customer/account/region/SSM host/kubeconfig reuse the existing non-revoked source under the installation advisory lock, preferring an active fresh connector. Other customers get distinct registrations/credentials. UI automatically reuses same-customer matches, refreshes the registry after creation, and handles a live registration returned by backend reuse without reinstalling. The previously pushed host-check UI remains compatible. Duplicate assessment creation now returns 409 ASSESSMENT_NAME_EXISTS via the existing customer/name constraint, including cancelled names, before writing history.

Validation: 78 focused backend tests and 44 frontend connection/discovery tests passed; frontend TypeScript and local production build passed. Installer tests execute its embedded Python with mocked Kubernetes/AWS/network calls, parse generated YAML for two different source IDs and a retry, and verify disjoint resource identities, correct references/selectors/read-only RBAC and stable same-registration reuse. No live AWS/source changes were performed by this fix. PROD remains frontend task :9 and prior API code until user deploys it.

Next: follow docs/migration/source-connection-prod-fix-20261023.md. Deploy the scoped PROD migration API code using existing deploy-migration-api-prod.py --prepare then --execute of its NEW printed release plan. Current PROD frontend can test installation after the backend fix; deploy the frontend candidate separately for the improved reuse/error UI. No database migration, registry/image collector rebuild, source connector image build or manual customer reassignment is required. Real PROD heartbeat/discovery/collection/export evidence remains pending. Broader UI redesign stays on hold.

---

## Source connection installation guard — 23 October 2026 (Asia/Kolkata)

Production frontend task :9 remains the last deployed revision. Authenticated testing found: the saved Db Schenker source SRC-9e51fbb33ad94ea482a24fa0b8a1c91c is PENDING_ENROLLMENT without an active heartbeat. A read-only PROD query also found JPMC India registration SRC-885c7419b2734265a70d91553d6c33d8 on the same physical SSM host/kubeconfig, status CONNECTED but no active connector heartbeat, with legacy corebanking DRAFT (discoveryMode absent). The existing backend treats that draft as an active assignment and blocks a competing installation. Customer-scoped listing correctly excludes the other customer's registration. Do not bypass the conflict or transfer ownership without an explicit customer decision.

The initial Db Schenker assessment DBS_Migration_Assessment_Prod was CANCELLED. Reusing its name produced a generic error; after choosing DBS_Migration_Assessment_Prod_02, the user screenshot confirmed a saved/linked draft and missing heartbeat. Duplicate name is consistent with the existing customer/name unique constraint, but no exception log was collected. Friendly duplicate-name handling remains a separate follow-up.

Frontend-only correction now uses the existing installationCheck API after saving a source and immediately before an AWS SSM installation. Missing/failed checks, denied access, active installation/assessment and any returned conflict prevent the install action; the API's explanation and Check host again appear beside verification. Even recoverable conflicts require the existing explicit recovery flow and cannot trigger an ordinary install. Previously connected registrations show Restore connector only when the host check is clear. Text distinguishes registration selection from a verified running connector. No backend/auth/database/ownership/source agent changes were made.

Validation: 25 focused source connection/validation tests passed, including eight new conflict/unavailable/retry/stale registration checks; TypeScript and a local production build passed. This UI fix is committed for review/deployment, not yet live in PROD. Next: decide whether this lab stays with JPMC or is intended for Db Schenker; resolve the association through an authorized recovery/retirement flow or use a separate host, then verify a recent heartbeat. UI correction alone cannot establish the connector. Broader UI redesign remains on hold.

---

## PROD frontend deployed — 23 October 2026 (Asia/Kolkata)

User terminal output confirms successful preparation and execution of /mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-prod-frontend-necjkwes/release-plan.json. Current deployed frontend: arn:aws:ecs:ap-south-1:905418045935:task-definition/navigan-frontend-TaskDefinition-j9W80aX9PBkf:9. Rollback task remains the same family :8. Built from branch commit b461886889d7c35d0b4aaf47fa9d5d0ef40420c9; immutable running image verified as 905418045935.dkr.ecr.ap-south-1.amazonaws.com/navigan/frontend@sha256:cfe98cb5d0627237424cd925a43939eb6d6d4a445750dd4c1c1370929e5f980e.

Release helper reported frontend deployment success, verified running image and passing public health/login HTTP checks. Backend/schema/workspace storage, scheduled repository collector and image polling service were already deployed and preflight verified. This supersedes historical frontend-pending/task-:8-live statements below. Do not rerun preparation or deployment merely to resume the session.

Remaining validation: fresh authenticated sign-in at https://navigan.click; Dashboard/Customer/Environment/Cluster navigation; Migration Overview and new assessment/discovery/scope/Collect & export workflow with PROD-specific source access. Real PROD collection/export and source-agent compatibility still need workflow evidence. DEV data was not copied into PROD. Deployment completion does not establish target readiness, workload migration or traffic cutover. Broader migration UI redesign remains on hold. Source agents and the unused extra recovery bucket were not changed.

---

## Frontend preparation timestamp fix — 23 October 2026 (Asia/Kolkata)

User ran frontend --prepare: live PROD backend/collectors, stable frontend and public Cognito preflight passed. Preparation then failed while serializing ECS taskDefinition.registeredAt (Python datetime) into original-task.json. It stopped before image build/push, task registration or service update. Last observed live/rollback task remains navigan-frontend-TaskDefinition-j9W80aX9PBkf:8. Failed private record directory: /mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-prod-frontend-n6886z5g; do not execute it as a release plan.

Fixed archival AWS response serialization to preserve datetime as ISO 8601. Candidate task JSON and baseline hashing remain strict; registration still excludes AWS response metadata. All 28 frontend release tests passed, including a full mocked --prepare with a real UTC registeredAt timestamp, saved rollback/candidate/plan verification and no service update. This is local regression evidence, not a live deployment.

Next: pull the branch and retry scripts/deploy-frontend-prod.py --profile navigan --prepare using the existing deployment venv and TMPDIR. After successful preparation, use only its newly printed release-plan.json with --execute. Production frontend rollout and authenticated smoke tests remain pending; broader UI redesign stays on hold. Existing backend/collectors remain deployed as recorded below.

---

## PROD collectors running / frontend release helper — 23 October 2026 (Asia/Kolkata)

User output confirmed the repository collector deployed as navigan-custmanagement-cfnstk-workspace-repositories with schedule ENABLED after starting the previously stopped shared Aurora cluster. The earlier InvalidResourceStateException stopped the repository deployment before writes; database availability is restored according to the successful retry. Do not repeat that investigation or restart databases without a current symptom.

Production image worker was built/pushed and deployed, then DesiredCount was explicitly changed from 0 to 1 using immutable image 905418045935.dkr.ecr.ap-south-1.amazonaws.com/navigan/prod-workspace-image-collector@sha256:cd025dfbba9aac18cf6e03431182ba87640fbd9d16fa11ec63325601c471573c. Task definition navigan-custmanagement-cfnstk-workspace-images-WorkerTask-NBdI3iULKHyk:1; role arn:aws:iam::905418045935:role/navigan-custmanagement-cfnstk-workspace--WorkerRole-ZTaZfknnEn2s; service navigan-custmanagement-cfnstk-workspace-images-WorkerService-yB0lavZw7aRs. Logs showed repeated processed:false without reported error codes (user supplied 23 Oct 13:56–13:57 UTC lines). This is successful startup/polling evidence, NOT a completed image-copy test. PROD registry-role metadata query returned []; no source-role trust changes were made. Private registries need authorization when configured later.

New scripts/deploy-frontend-prod.py follows the existing immutable-image/copy-current-task release method. Default readiness is read-only. --prepare verifies PROD API/schema/storage, repository schedule, image worker, stable frontend and actual public Cognito settings; exports committed frontend via git archive into private TMPDIR (no new worktree, no local reset/cleanup); builds/pushes an immutable ECR image; registers a candidate copied from the current task. Only frontend image and runtime MIGRATION_SOURCE_FIRST_ENABLED=true differ. User-modified next-env.d.ts and local env files are preserved/excluded; no .env/config file is sourced. Roles, API origin/path, task sizing/network/health/logging/sidecars and production NODE_ENV are preserved. Reserved AWS registration metadata/tags are excluded.

Preparation prints the actual candidate/image/release-plan path without updating the service. --execute re-verifies backend, baseline, exact candidate diff and digest, then updates only the known Navigan frontend service. It checks final service revision and all running image digests, plus public /healthz and /login HTTP 200. Circuit-breaker rollback cannot count as success. The saved prior task remains the rollback reference; no blind automatic rollback is added.

Validation: 143 focused Python release tests passed (26 frontend helper checks plus existing 117); earlier 28 frontend switch/proxy tests, TypeScript and production build passed. No frontend source changed in this helper addition. Immediate next action: user pulls and runs scripts/deploy-frontend-prod.py --profile navigan --prepare with deployment venv/TMPDIR. Frontend live remains last observed task :8 until actual execution output confirms a change. Authenticated platform/migration workflow, real PROD collection/export and target readiness are still pending. Broader UI redesign stays on hold; source agents and extra recovery bucket remain untouched. See docs/migration/production-release-20261023.md.

---

## PROD API deployed / collectors and frontend switch prepared — 23 October 2026 (Asia/Kolkata)

User output explicitly confirmed successful scoped production API execution using /mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-prod-migration-api-uyvrnt7c/release-plan.json. Root change set navigan-prod-migration-api-9b194225c17642db/1096740c-2e2f-424d-9897-ad349214fdba completed; script verified the deployed package checksum and PROD workspace/source-first settings. Nine protected artifact routes, discovery policy and source invoke permission were added. MigrationIntegration was verified unchanged. This supersedes API-preparation-only status. Authenticated workflow smoke testing is still pending.

New scripts/deploy-workspace-workers-prod.py binds the tested reusable collector deployment to PROD database navigan, parent navigan-custmanagement-cfnstk and ECR navigan/prod-workspace-image-collector. It verifies actual API identity/role/revision, source-first flag, table/grant state and actual workspace bucket/KMS settings before delegation. Existing DEV script defaults remain DEV through explicit DATABASE/LABEL constants; no DEV target is changed by the production entry point. The wrapper rejects local source/collector edits and leaves unrelated frontend local files alone. Reusable deploy code now validates the exact ECR repository and bounds Docker pushes at ten minutes with the local image retained for recovery.

Immediate next actions: user pulls and runs production wrapper --repository --enable-schedule --apply, then --image --apply. Repository deploys a dedicated scheduled Lambda; image mode builds/pushes a PROD image and stages a separate private image service at zero tasks. No API, source connector, source role trust or frontend is updated. Capture actual outputs before claiming collector deployment. Exact registry-role authorization/trust/private networking must be checked before starting images. Do not reuse a DEV image/repository or turn on tasks blindly.

Frontend source changes are prepared only: shared isSourceFirstEnabled server switch accepts explicit MIGRATION_SOURCE_FIRST_ENABLED=true in PROD and retains existing DEV defaults. Four migration server routes await Next.js connection() so the flag is read at request time. NODE_ENV remains production; authorization and preview access are unchanged. A future ECS task must explicitly enable the flag after backend readiness. No frontend image/service deployment occurred; last observed rollback baseline remains task :8.

Validation passed: 117 focused Python tests, 28 frontend switch/proxy tests, TypeScript and production Next.js build. All four migration routes are dynamic in the build output. These are code/mocked checks, not live collector or authenticated UI acceptance. See docs/migration/production-release-20261023.md for concrete commands and the confirmed storage/API resource details. The extra recovery bucket remains untouched. Broader UI redesign stays on hold; agent still has no AWS credentials/CLI/Docker.

---

## API preparation guard correction — 23 October 2026 (Asia/Kolkata)

User ran API preparation at 800f157. PROD database/storage/API identity/JWT checks passed; GitHub App configuration is present. Private rollback/release record: /mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-prod-migration-api-hs_2r1sy. Root change set arn:aws:cloudformation:ap-south-1:905418045935:changeSet/navigan-prod-migration-api-9638b77362554e10/773fa6c8-e14d-43e3-87a4-db62e8d64343 was created but NOT EXECUTED. Inspection printed Modify MigrationFunction then stopped at Unexpected nested resource change: MigrationIntegration. The release-plan.json was not written because the scope guard failed. API/frontend remain unchanged; do not execute that earlier change set manually.

The initial guard was too narrow for potential CloudFormation dependency re-evaluation. The correction does NOT blindly allow integration changes: it fetches current and proposed processed child templates from AWS and requires complete equality of every dependent resource definition. Only unchanged MigrationIntegration AWS_PROXY, JWT routes referencing MigrationIntegration, and API Gateway invoke permissions referencing MigrationFunction may be non-replacing Modify dependencies. Changed properties/security/targets, other integrations, connector/role-trust changes, additions through this exception, deletions and replacements remain blocked.

Ninety-two focused release tests pass, including full-template equality checks, changed integration/JWT/invoke-permission rejection, replacement rejection, protected target constraints and use of both actual AWS template reads. These are mocked tests; the actual dependency equivalence remains to be verified by the next live preparation.

Immediate next action: user pulls the correction and reruns the same --prepare command. It prepares a fresh scoped plan; the earlier backup/change set are preserved. Do not recreate storage, delete the extra recovery bucket, rebuild frontend, or claim API deployment succeeded. After successful preparation review output and use its actual new release-plan path for execution. Remaining collectors, connector/workflow compatibility, frontend production feature switch, image build/rollout and smoke checks are still pending.

---

## PROD storage verified / API preparation — 23 October 2026 (Asia/Kolkata)

User supplied successful storage deployment output and describe-stacks evidence: both navigan-custmanagement-cfnstk-artifact-workspace and navigan-custmanagement-cfnstk-source-recovery are CREATE_COMPLETE. The older script was run before the single-bucket correction. Workspace bucket: navigan-custmanagement-cfnstk-arti-workspacebucket-xc7zf8yedqxl; owner 905418045935; KMS key arn:aws:kms:ap-south-1:905418045935:key/61119b9e-0d25-4459-9a2d-7e13dbb93568. Extra legacy recovery bucket: navigan-custmanagement-cfnstk-sourc-recoverybucket-y0q8hr09sgsl. Leave it untouched; use only the workspace bucket for this workflow. Private storage record: /mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-prod-migration-storage-2icl083o. Workspace table/runtime-grant verification passed in that output. This supersedes earlier storage/schema-pending status.

New scripts/deploy-migration-api-prod.py prepares a scoped API release without execution (--prepare), or executes an exact saved private plan (--execute PLAN). Default invocation is read-only. It saves original API ZIP/config and live processed parent/child templates, preserves existing dependencies and parent parameters, bundles current migration modules plus the shared GitHub App helper and pinned Lambda-compatible PyYAML. It binds the workspace bucket/KMS key, enables the backend source-first flag, adds only protected migration/source-setup/artifact routes using existing JWT settings, and attaches a scoped discovery policy to the actual PROD API role. Existing PROD GitHub App references may be copied from ClusterFunction; missing references are reported. It never updates connector Lambda, source agents, role trust, collectors or frontend.

The root change set must include nested details and change only MigrationManagement; the child may change only MigrationFunction, the dedicated policy, source invoke permission and explicitly listed JWT routes. Any connector/role-trust/unrelated stack/destructive/replacement changes stop preparation/execution. Execution also rejects stale stack/Lambda revision/checksum. Non-auto-deployed API stages or unprocessed/non-JSON templates stop readiness rather than guessing. These are guards, not evidence the live preparation has succeeded.

Validation: 76 focused mocked release tests pass (35 API, 26 storage, 15 migrations). No AWS API preparation/execution has been run by the agent, which still lacks AWS credentials/CLI/Docker. Immediate next action: user pulls and runs --prepare with deployment venv/profile navigan/existing TMPDIR; inspect the actual proposed changes and printed release-plan path before running --execute. API live execution, collector provisioning/registry access, connector compatibility/workflow smoke checks and frontend feature-switch/immutable image rollout remain pending. Known frontend rollback baseline remains :8. Broader UI redesign stays on hold.

See docs/migration/production-release-20261023.md for the concrete command sequence. Do not rerun storage provisioning or delete the extra bucket as part of API preparation.

---

## Single workspace bucket correction — 23 October 2026 (Asia/Kolkata)

User terminal output explicitly confirmed migrations 027/028 and runtime grants committed successfully to PROD database navigan. This supersedes the earlier ambiguous “done” and missing-table preflight. Production frontend/API promotion remains pending.

The user clarified DEV has one workspace bucket. Inspection of current artifact_recovery.py confirms workspace-bound LIVE_DEFINITION/HELM_RELEASE recovery uses artifact_workspace.storage_configuration(), the same workspace bucket and KMS key. MIGRATION_RECOVERY_BUCKET is only the older recovery path without workspace binding. The assistant incorrectly described two buckets as the established DEV requirement and unnecessarily included the legacy recovery stack in the initial PROD storage script.

The corrected scripts/deploy-migration-storage-prod.py provisions only navigan-custmanagement-cfnstk-artifact-workspace. It retains identity/schema/grant checks, checked change sets, ownership/KMS/versioning/privacy verification, and no changes to API code/config, frontend or source agents. It neither deletes nor repurposes existing buckets. Forty-one focused tests pass, including exact one-stack execution and rejection of legacy recovery scope.

IMPORTANT: after the correction was being prepared, the user stated they ALREADY RAN the previously provided storage script. Do not assume the earlier missing-table preflight is their only storage invocation. Both workspace and separate legacy recovery stacks MAY now exist. No successful post-migration storage output has been supplied yet. Next obtain read-only describe-stacks output for the two exact PROD storage stack names, preserve all resources, and use the existing workspace bucket if verified ready. Do not ask the user to rerun provisioning blindly or delete the extra bucket. Any later cleanup requires checking objects/references and a concrete separately authorized action. Continue toward scoped API/collector/frontend release after verifying storage.

This section supersedes earlier two-bucket deployment instructions and earlier schema-pending status. The broader UI redesign remains on hold; task :8 stays the recorded production frontend rollback baseline. See docs/migration/production-release-20261023.md.

---

## Storage release preparation — 23 October 2026 (Asia/Kolkata)

Current task remains the user-authorized PROD frontend/backend deployment. After the runner guard fix `cb7c538`, the user replied “done” to rerunning the workspace migration. Treat this as user-reported completion, not independently observed commit output. The next script verifies PROD identity, all three tables and all runtime grants before making changes.

New release utility: `scripts/deploy-migration-storage-prod.py`; runbook: `docs/migration/production-release-20261023.md`. Default invocation is read-only. With --apply it prepares both dedicated PROD storage change sets, validates resource allowlists and rejects removals/imports/replacements, rechecks the actual production API revision/role, then executes. It binds storage policies only to the actual PROD MigrationFunction role. It verifies ownership, encryption, versioning and public-access blocking after deployment. Existing matching stacks/no-op updates are supported; unexecuted CREATE preparations can be resumed. Records are private under TMPDIR. No parent stack, Lambda code/config, API routes, ECS, source host, authentication or database writes are part of this utility.

Validation: 39 focused tests passed (24 production-storage boundary tests plus 15 scoped migration tests). These are mocked AWS tests, not a live cloud deployment. New script/tests/runbook and this checkpoint are prepared/published together; use the actual remote branch HEAD rather than sandbox master.

Immediate next action: user pulls and runs the PROD storage utility using the deployment venv, profile navigan and existing TMPDIR, with --apply. Expected completion: “PROD migration storage deployed and verified. API configuration/code and frontend are unchanged.” Record the actual output before declaring storage ready. API promotion, collectors, explicit production frontend feature switch, immutable frontend build/service rollout and smoke tests remain pending. PROD frontend rollback baseline stays task :8. The agent still has no AWS credentials/CLI/Docker. Broader UI redesign stays on hold.

---

## Production release override — 23 October 2026 (Asia/Kolkata)

The user explicitly requested deployment of both frontend and backend to PROD. This supersedes earlier frontend-only/no-PROD scope for this release; the broader workflow redesign remains on hold. Follow the existing controlled release standard in MASTER_CONTEXT section 10: immutable frontend image, copy the current production task definition changing only the image, scoped migration backend change set, preserve unrelated stacks/connector/authentication, smoke tests and rollback. Do not use DEV deployment scripts against PROD or deploy the full parent stack blindly.

User WSL output verified branch `new_migration_approach_18oct26` at `bd44e25`, AWS account `905418045935`, region `ap-south-1`, production frontend task `navigan-frontend-TaskDefinition-j9W80aX9PBkf:8` with desired/running 1/1 and rollout COMPLETED. Preserve this rollback target. Existing user changes: modified `frontend/next-env.d.ts` and untracked local registry/result files; do not reset, clean, delete or create another worktree.

Production nested migration stack: `navigan-custmanagement-cfnstk-MigrationManagement-15LMVISK00HR5`, UPDATE_COMPLETE. MigrationFunction `navigan-custmanagement-cfnstk-Mi-MigrationFunction-nYtXL48n5mkD` is Active on python3.12, DB_NAME `navigan`. Its inspected environment has no source-first/workspace configuration. Read-only SQL confirmed source_clusters exists, but artifact_workspaces, workspace_artifacts and workspace_collection_jobs are absent.

The attempted workspace-only migration stopped before AWS/DDL with “--workspace-only requires --database navigan_dev”. The assistant had missed the separate DEV-only guard when giving the command. The runner is now corrected to accept only navigan_dev or navigan in scoped mode; navigan additionally requires the exact existing --confirm-production-database navigan confirmation. Only migrations 027/028 and their scoped grants are selected. Fifteen focused mocked Data API tests pass, covering confirmation before AWS calls, no-AWS dry run, scoped PROD commit, rollback/identity mismatch, unrelated database rejection and existing DEV behavior. SQL files are unchanged.

Immediate next action: user pulls the runner correction and reruns the workspace-only dry run and migration with --database navigan --confirm-production-database navigan. Do not record success until their output confirms the commit. Then prepare PROD-only workspace storage, scoped API/routes/recovery and collectors as required. Current new migration frontend routes are development-only; prepare an explicit production feature switch without enabling development mode or preview permission bypasses before building the frontend. No production code, schema, storage, workers or frontend deployment has succeeded in this release yet.

The agent sandbox lacks AWS credentials/CLI/Docker and cannot execute the cloud release directly. User runs concrete reviewed commands from the existing WSL checkout. Continue using the actual remote branch tree for selective GitHub publishing; never push the sandbox master tree.

---

# Current checkpoint — 23 October 2026 (Asia/Kolkata)

Read `NAVIGAN_SESSION_HANDOFF_2026-10-23_LATEST.md` first. Older checkpoints below are historical.

| Field | Latest recorded state |
|---|---|
| User branch | `new_migration_approach_18oct26` |
| Verified remote feature HEAD | `ba88ea15ac73aea34657ed8316685d2012c1e28e` |
| User checkout | `/mnt/b/Langchain_Ai/Navigan-migration-test` |
| Artifact DEV work | Schema 027/028, workspace API/routes/storage, repository and image workers deployed per user command output |
| Runtime acceptance | All 12 displayed collection jobs succeeded; final export downloaded successfully with 14 collected artifacts / 2 historical exclusions |
| Source recovery | Headlamp Helm/image saved; expired retailflow Jobs reviewed as historical; parent CronJob definition/image collected |
| Export feedback fix | `ba88ea15`: visible pending/error/result and download next to action; 38 focused tests/typecheck/build passed; live API outcome not independently verified |
| Files & images release | `bc87adf7`: Check sources → Collect & export; one workspace toolbar; named artifact/source/progress table; active read-only polling; existing guards retained |
| Overview release | `8236e585`: lifecycle/approval donuts, Graphite theme, compact provider logos, one expandable queue; existing assessment actions retained |
| Latest user acceptance | Overview: “much better” — accepted visual baseline |
| Checks | Latest collection follow-up: 73 focused tests; Overview: 11 focused tests; TypeScript/build passed; browser fixture checks at six widths 390–1920px |
| API limitation | Workspace read responses omit persisted object storage details; folder shown after explicit export, exact artifact/receipt paths in downloaded manifest |
| Deferred | Entire migration workflow UI/UX redesign explicitly on hold |
| Not completed | Target readiness, target import/deploy, persistent-data migration, traffic cutover, PROD rollout |
| Immediate action | User review of merged collection/export after frontend pull/restart; broader redesign remains on hold |
| Current live AWS state | Not reverified in UI sessions; historical deployment output is not a new health check |

---

## Preserved checkpoint history — superseded as current state

# Navigan — Daily Session Checkpoint

**Current:** 20 October 2026, 01:15 IST. Read `NAVIGAN_SESSION_HANDOFF_2026-10-20_0115_IST.md` first. Earlier checkpoints below are historical and do not describe the current discovery blocker.

| Field | Current recorded state |
|---|---|
| DEV branch | `new_migration_approach_18oct26` |
| Latest published remote commit | `2cfb422d018d7005ae84d182dde68ed0f2edfecb` — compact discovery table and evidence drawer |
| User checkout | `/mnt/b/Langchain_Ai/Navigan-migration-test` |
| Backend/connector last user-confirmed upgrade | `69a61b4`, two DEV migration Lambdas and existing DB Schenker connector upgraded |
| Runtime acceptance | User reported discovery/assessment completed and all registry entries Available |
| Source Retailflow | Six images mirrored into source-account ECR; seven controller rollout/health checks passed; target unchanged |
| Latest UI acceptance | User approved combined latest Option 1 table + Option 2 drawer; implementation pushed; final user pull/render not explicitly confirmed |
| Tests / build | 53 focused frontend tests, TypeScript and production build passed; wider suite retains 25 baseline failures |
| Browser QA | Desktop tabs/search/disclosures/drawer/focus verified with fixtures; full-width 390px drawer checked |
| Latest observed totals (user-reported) | 8 namespaces, 35 workload controllers, 479 resources, 438 source findings |
| Open issue | Exact resource-kind/finding-code breakdown unknown; raw labels/grouping are confusing |
| First next task | Readonly count breakdown, then clearer application/platform and grouped-finding presentation while retaining complete discovery |
| Not done | No count grouping/label fix after this question; no target migration/traffic cutover; no PROD changes |
| Deployment required for latest UI | None beyond frontend pull/refresh; do not rerun Lambda/connector deployment for this UI-only change |
| Rollback reference | UI parent `69a61b4`; review a scoped UI revert against current remote head rather than hard-resetting other work |

User requested stopping for the night. Resume at the next morning session. Full release/evidence details and saved source backup/result paths are in the latest handoff. No secrets belong in this kit.

---

## Preserved earlier checkpoints — superseded as current state

# Navigan — Daily Session Checkpoint

**Updated:** 19 October 2026, Asia/Kolkata. Last runtime evidence: 18 October.

Read `NAVIGAN_SESSION_HANDOFF_2026-10-18_EOD.md` first.

| Field | Current recorded state |
|---|---|
| DEV branch / release | `new_migration_approach_18oct26` / `428cd3bc2298734e96e5cab5be44ce9dd9781aca` |
| User checkout | `/mnt/b/Langchain_Ai/Navigan-migration-test` |
| Implemented | Source connection Option 4, tooltips and validation, draft editing, stable install progress and single Connect/Verify action, source discovery/assessment UI, source-only engine, workspace completion gate |
| Tests | 30 frontend and 65 selected backend tests; TypeScript and preview build passed |
| DEV deployment | User confirmed both migration Lambda packages updated using `deploy-source-connection-screen-dev.py --profile navigan --apply` |
| Customer facts | DB Schenker/JPMC real; other records dummy. DB Schenker chosen for migration context |
| Live acceptance | Not complete: DB Schenker detailed inventory/report remain null |
| Blocker | Pending migration references `SRC-2f0e434335e04ef0bdccd74cb3322f2c`; healthy running connector serves `SRC-ae85e62d759d47fabf8eb87610ea39b9` and is IDLE |
| First next task | Verify registration ownership and migration references through authorised API reads; prepare supported association repair |
| Deferred | Shared-cluster customer grants/deduplication, later workspace redesign, AI/artifact pipeline and execution |
| PROD | No deployment this session; historical last-confirmed task :8 is not reverified |
| Recovery pointer | Full IDs/evidence and deployment backup path in the 18 Oct EOD handoff |

No connector reinstall, source/customer reassignment, registration deletion/merge or workload migration has been performed to fix the mismatch. Do not infer success from a healthy pod or blank logs.

---

## Preserved checkpoint history

# Navigan — Daily Session Checkpoint

> **LATEST SESSION (17 October 2026 EOD):** Read `NAVIGAN_SESSION_HANDOFF_2026-10-17_EOD.md` first. Architect ideation compared against actual migration code; 67-row tracker delivered in Library (16 established / 17 partial / 26 not implemented / 8 decisions). Architecture alignment and an EKS application-centric pilot are next; no code/infra mutations during review. Last user-confirmed PROD is ECS frontend `:8` from login commit `84ea9ee`, not historical `:6` or `:5`. The 16 Oct checkpoint below is preserved only for history.

> **SUPERSEDED AS THE CURRENT CHECKPOINT:** This is the historical 16 October *morning* checkpoint. For the verified close-of-day state, GitHub branch `0179edb` theme and production ECS revision `:6`, read `NAVIGAN_SESSION_HANDOFF_2026-10-17.md` first. Do not treat the older `:5` or `codex/migration-intelligent-planning` references below as current.

**Last updated:** 2026-10-16 (Asia/Kolkata)
**State:** Historical checkpoint; verify live state before changes.

## Confirmed current position
- **DEV:** Local Next.js frontend at `http://localhost:3000`; working source branch `codex/migration-intelligent-planning` in `/mnt/b/Langchain_Ai/Navigan-migration-test`. User confirmed **Open Migration Workspace** is now working following branch correction.
- **PROD:** `https://navigan.click` login working per user; navigan-frontend ECS task definition `navigan-frontend-TaskDefinition-j9W80aX9PBkf:5` had rollout **COMPLETED**, desired/running **1/1** on Oct 16.
- **PROD frontend digest:** `sha256:6bc86cc7a37a933a4d144ccdc64d5f24281e1c2b4c5a2ee620242be82542baa8`.
- **Backend:** Isolated production Migration Management Lambda/routes deployed. PROD SQL migrations `025_migration_planning_drafts.sql` and `026_migration_target_assessments.sql` applied.
- **Incident resolved:** Frontend `.env.local` OIDC Client ID had an invalid trailing carriage return (`\\r`); file normalized, frontend rebuilt and deployed. Authentication restored after release `:5`. Historic rollback to `:3` did not resolve login.
- **Known code trap:** The local `release/migration-review-export-20261016` branch did **not** contain the Migration Planning `/plan` page and `planning-workspace.tsx`; `codex/migration-intelligent-planning` does. Check the branch before investigating role/access.

## Pending validation / decisions
- End-to-end production Migration workflow: Source → Target → Compatibility → Remediation → Plan → Review & Export.
- Save Draft, Resume Draft, assessment accuracy, topology dependency coverage and export acceptance.
- Three previously failing connector-related tests remain excluded/unresolved; connector changes are out of approved migration scope.
- Design/implement gated DEV/PROD CI/CD (GitHub Actions, AWS OIDC, immutable images, isolated change sets, protected environments, smoke tests and rollback).
- DEV AWS API and database names/URLs, and complete live API catalog, need read-only verification before editing/deploying.

## Boundaries
- **Never touch:** `nimbusops-frontend-cluster`, `MigrationConnectorFunction`, source/cluster connector and RBAC, private EKS/GitOps, tools-gateway, unrelated services/databases.
- **No migration execution:** only assessment, readiness, planning and export.
- **No production changes without explicit approval.** Keep working production frontend `:5` intact.

## Today's work (update at the end of each session)
| Field | Value |
|---|---|
| Date (Asia/Kolkata) | 2026-10-16 |
| Today's objective | Establish repository-based master context and daily checkpoint routine |
| Current DEV branch / commit | Branch last confirmed `codex/migration-intelligent-planning`; commit **not rechecked** |
| Working tree | **Not rechecked**; earlier showed an untracked file named `\\` on release branch |
| Work completed | Master context and starter checkpoint prepared; repository commit pending |
| Tests / build results | No code changes or build in this documentation step |
| Deployment | None for this documentation step |
| Risks / blockers | Historical snapshots can become stale; run scoped read-only checks |
| Next task | Validate migration workflows; then design safe automated CI/CD |
| Approvals required | Explicit approval for production deployments or scope expansion |
| Rollback pointer | Production ECS prior task/image metadata in Master Context; reverify before use |

## Update instructions
1. Replace the table values with facts verified **during the session**; annotate unknowns instead of guessing.
2. Add relevant PRs/commits, exact paths, test counts, build digests, deployments and user acceptance outcome.
3. Keep the previous checkpoint in Git history; commit updated file in a reviewable PR.
4. Never paste secret values, passwords, cookies, authorization codes or full auth callback URLs here.
