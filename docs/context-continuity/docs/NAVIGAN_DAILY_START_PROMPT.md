## 27 October 2026 — production audit reviewed; scoped bootstrap release helper ready

**Verified from the user's audit:** both production ClusterFunction and StatusFunction packages still generate Falco chart 9.1.0 without the corrected image/plugin pins. Installer failure polling is absent. The production Terraform runner is pinned to image digest `565d9da23955ec84ba906e0ebb07d9cc5c1fac8d9fce23fc72cc05e6fcd283b0`, has no protected-pool plan guard, and its module differs from current source in main.tf, variables.tf and outputs.tf.

**Scope decision after reviewing the supplied code diff:** do not replace the runner/module with the complete branch source. That would also promote unrelated networking, adopted-node-group/migration and deletion behavior. The release builds an overlay on the exact deployed image. It adds only purpose normalization, protected-pool certification/apply checks, node labels/taints and the Terraform purpose type. Existing security groups, resource addresses, outputs, deletion checks, dependencies and other runner functions remain as deployed.

**New release tooling:** `scripts/cluster-bootstrap-patch.py` patches captured live code with AST preservation checks. `scripts/deploy-cluster-bootstrap-prod.py` updates the two Lambda ZIPs and the runner image through the existing production parent/ClusterManagement CloudFormation hierarchy. ClusterFunction receives failure polling and Falco defaults; StatusFunction receives Falco defaults only. Unrelated ZIP members and runtime configuration remain intact. The script reuses the existing private versioned workspace bucket and ECR repository; it adds no IAM, API, frontend or customer-cluster resources and starts no installer/cluster build.

`--prepare` builds/pushes the overlay, uploads versioned artifacts and creates an unexecuted change set. `--apply` additionally executes after checking the live capture, parameter bindings, exact template delta, change-set scope and absence of replacements. `--execute PLAN` resumes a prepared release after repeating the same checks. The expected effective changes are ClusterFunction.Code, StatusFunction.Code and TerraformProject.Environment.Image. Parent and child templates/configurations, original ZIPs, prepared packages and the plan are saved privately for review/recovery.

**Validation:** 155 targeted tests passed; git diff --check passed. The narrow Terraform overlay parses successfully. Tests cover preservation of legacy destructive-plan rejection/network behavior, only the intended package changes, stale runtime rejection, runner overlay contents and rejection of unrelated/replacing/incomplete CloudFormation changes. The historical runner/module fixture is reconstructed from the supplied diff for regression tests; it is not claimed to match the live artifact byte hash. Actual preparation checks captured files against the pinned ECR image.

**Runtime deployment remains pending.** No AWS deployment or Docker build was performed by this session. From the existing feature-branch checkout, pull the new helper and run:

```bash
/mnt/b/Langchain_Ai/navigan-deploy-venv/bin/python scripts/deploy-cluster-bootstrap-prod.py \
  --profile navigan --capture /var/tmp/navigan-bootstrap-audit-8n_7dlrj --apply
```

Use the final `PROD bootstrap release verified` message as the deployment check before creating a fresh cluster. Then verify system labels/taint, two Ready system nodes, Falco 0.45.1/Ready, required components Ready, lifecycle ACTIVE and all four tool launches. If capture freshness or scope checks stop the release, inspect the error rather than bypassing the checks. Keep private capture/release records local and share only the printed summary/error. After promotion refresh the private SAM baseline; full branch/source parity is still not implied because unrelated newer source behavior was deliberately excluded.

## 27 October 2026 — new-cluster prevention source ready; runtime deployment pending

The user authorized permanent fixes before retesting new-cluster creation. Existing cluster recovery remains verified as recorded below; it does not prove that newly generated clusters use the new defaults.

**Implemented in source:**

- Both the packaged system repository template and the platform scaffold use Falco chart 9.2.0, explicit Falco image 0.45.1 and container plugin 0.7.5 with modern eBPF and protected-system-node scheduling. The scaffold catalog matches the new Falco versions.
- The Terraform runner rejects plans whose managed SYSTEM node groups lack the platform-services/system-purpose labels, system-only NoSchedule taint, or minimum/desired capacity of two. It checks the intended Terraform resource address and node-group name, including no-op resources, during certification and again before applying an approved saved plan. ADOPTED groups remain outside managed-resource checks.
- Authorized cluster detail, platform-components and tools polling checks the exact recorded customer-account installer build. Verified FAILED/FAULT/STOPPED/TIMED_OUT states become BOOTSTRAP_FAILED with an INSTALLER_BUILD_* failure code and version/history/audit records. Unknown lookups retain the existing lifecycle state. Account, region, project, registered connector and execution identity are checked; locks reject results from superseded installations. Build success alone never activates a cluster or bypasses component health.
- Added scripts/audit-cluster-bootstrap-runtime.py. It reads the requested stable parent/ClusterManagement stack, captures the two Lambda ZIPs/configurations and Terraform project, and prints a summary excluding runtime secrets. Optional --inspect-runner resolves the deployed ECR digest and copies runner/module files from an unstarted Docker container. AWS operations are read-only. Private captures must remain local; share only summary.json.

**Validation:** 130 targeted tests passed covering cluster behavior, connector installation, capabilities, tool access, generated Falco manifests, plan protection, stale/terminal installer results, the detail API failure response, and audit target/secret/read-only/container-start constraints. git diff --check passed. No live AWS deployment, Docker build, Terraform validation or fresh-cluster acceptance test was performed in this environment.

**Next action:** run the read-only production audit from the existing project checkout after pulling this branch:

```bash
/mnt/b/Langchain_Ai/navigan-deploy-venv/bin/python scripts/audit-cluster-bootstrap-runtime.py \
  --profile navigan --region ap-south-1 --environment prod \
  --stack-name navigan-custmanagement-cfnstk --expected-database navigan \
  --inspect-runner
```

Review that summary and prepare a scoped CloudFormation release based on the captured live processed templates and ZIPs. Preserve unrelated deployed code/configuration, IAM, authorization, API routes and the separate frontend release. Update both ClusterFunction and StatusFunction packaged Falco templates, add failure polling to ClusterFunction, and rebuild/pin the runner with the protected-node module and plan checks. Do not use a broad branch SAM deployment or the older deploy-system-node-migration-dev.sh helper: known source/live package differences must first be accounted for. No AWS runtime changes were performed in this session. Continue the authorized scoped fix without repeating historical deployments or restarting the recovered cluster.

**Acceptance pending after runtime promotion:** create one fresh cluster; confirm the managed system pool has its labels/taint and two Ready nodes, the generated Falco manifest uses the corrected artifacts, all required components become Ready, the lifecycle reaches ACTIVE, and all four tools launch. Verify a controlled installer terminal-failure case in a test environment surfaces the failure without requiring a manual restart.

## 27 October 2026 — cluster platform services recovered (verified)

This recovery entry supersedes older blockers for `dbs-demo-cluster-creation` only. Preserve the historical entries below.

**Verified outcome:** user confirmed Headlamp, Argo CD, Prometheus and Grafana buttons are enabled and all four tools launch. The final dashboard screenshot reports nodes 2/2 Ready, pods 24/24 Ready, workload replicas 48/48 Ready and 100% readiness. Falco's live DaemonSet was independently verified 2/2 Ready with image `docker.io/falcosecurity/falco:0.45.1`. No further bootstrap restart is indicated.

**Applied recovery:**
- The original installer failed because the system node group lacked `navigan.io/platform-services=true`, although two nodes were Ready. User added this label through the managed node-group configuration and verified the update succeeded, then restarted bootstrap once. The connector and Argo CD installation completed successfully.
- Falco then repeatedly crashed while loading its modern eBPF `signal_deliver` probe. Logs matched the upstream kernel-verifier compatibility issue on AL2023 kernel 6.18.54 (Falco issue 4017 / libs fix 3119).
- In the cluster's existing system GitOps repository, the user reviewed and pushed commit `76adb56ed04d519ce3cfbb95175740901e0fda57` to `main`: Falco chart 9.1.0 -> 9.2.0; explicit Falco image tag 0.45.1; container plugin reference `ghcr.io/falcosecurity/plugins/plugin/container:0.7.5`. Existing driver mode, node selector, tolerations and resource limits were retained.
- Argo CD subsequently synced that exact commit successfully. An earlier report still showing chart 9.1.0 preceded reconciliation; the later diagnostic verified the updated image and 2/2 Ready. A successful diagnostic build by itself was not proof of component health.
- Component health and tool-launch access use separate checks. No gateway, permission or tunnel change was applied; no exact /tools disabledReason was captured. The final cluster lifecycle/ACTIVE field was not separately supplied.

**Prevention work remains pending:** ensure newly provisioned system groups receive the required label; update Navigan's platform/system-repository templates with compatible Falco pins; propagate installer failures into backend/UI status. These source/deployment changes were NOT implemented by the live repair. The recovery commit belongs to the cluster's system GitOps repository, not shankamal/Navigan.

This note records the user-confirmed recovery only. It does not declare global DEV/PROD SAM or Lambda-source parity complete, authorize unrelated deployments, or resume the deferred broader migration UI redesign. Current source/runtime differences must be inspected before preparing any prevention change.

---

## Latest checkpoint — 25 October 2026

Read [NAVIGAN_SESSION_HANDOFF_2026-10-25_LATEST.md](./NAVIGAN_SESSION_HANDOFF_2026-10-25_LATEST.md) first. It supersedes conflicting status in older entries below.

- Accepted login: one logo beside Welcome to Navigan; approved new slogan; Deloitte-green button; smaller provider logos; latest compact controls and 36% dark panel in `6916e11`.
- PROD frontend revision 22 confirmed COMPLETED. Revision 23 prepared; execution not confirmed. Exact image/plan and validation limits are in the latest handoff.
- Identical duplicate ECR response fix `d148e62` tested (33 tests); already pushed.
- Disabled cluster-tool incident resolved after worker capacity returned: `dbs-sims-clus2-system-ng` had desired size 0. User confirmed healthy tools and enabled buttons. No reinstall or code fix for this incident.
- Stale health reporting and broader UI consistency remain deferred. No new auth/backend/gateway changes requested.

---

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

# Navigan — current continuation prompt (23 October 2026)

Continue Navigan from the accepted state; read `docs/NAVIGAN_SESSION_HANDOFF_2026-10-23_LATEST.md`, then the latest checkpoint and master override. Older handoffs are history, not today's blockers or task list.

Repository: https://github.com/shankamal/Navigan
User path: `/mnt/b/Langchain_Ai/Navigan-migration-test`
Active branch: `new_migration_approach_18oct26`
Latest verified feature HEAD: `ba88ea15ac73aea34657ed8316685d2012c1e28e`.

Before edits run `git branch --show-current`, `git status -sb`, `git log -8 --oneline`. Preserve all local files; do not reset, clean, delete, create another worktree or push synthetic agent master history. Freshly verify remote HEAD when publishing.

Completed: DEV workspace schema/API/storage and collectors; user-reported all 12 collection jobs succeeded; final JSON export successfully downloaded with 14 collected artifacts and 2 historical exclusions. Exact object versions/checksums/image digests/receipts are recorded by export. Target readiness, target deployment, data migration and traffic cutover are NOT complete.

Recent frontend work: discovery/assessment separated from scope/files; source connection setup/reference removed from discovery (handled during creation); scope workload Select all/Deselect all respects namespace/search filters and explicit saving. Files & images follow-up at `bc87adf7`: Check sources → Collect & export (no separate review stage), one workspace action toolbar, and one named artifact table with GitHub/registry/source-cluster origin and saved/queued/copying/failed progress. Jobs map by artifactId. Overall percent counts required artifacts saved; active per-copy bars are indeterminate because there is no byte-progress API. Read-only updates run every five seconds only for active visible pending work and stop on completion/leaving/error. Existing permissions, stale/scope/creation/export guards are retained. User acceptance of this follow-up is pending. Current read API omits persisted storage details; exact artifact/receipt paths remain in the downloaded manifest. Do not fabricate paths or claim that limitation is solved.

Latest accepted visual baseline: Migration Overview at `8236e585` — user said “much better”. Preserve Neutral Graphite/charcoal, Geist theme font tokens, compact responsive layout, colored provider logos/donut charts, deep-green actions, neutral cards (no pale-green fills), shared PageHeading and the accepted legacy-offset reset. Overview has one expandable attention queue and preserved list/board/filter/actions. Latest collection follow-up: 73 focused tests; Overview: 11 focused tests; TypeScript/build passed; preview checked at six widths 390–1920px. Do not claim the full test suite or live AWS workflow was revalidated by fixture QA.

IMPORTANT: the broader migration workflow still needs substantial UX improvement, but the user explicitly put that redesign ON HOLD. Record this; do not start it automatically. Current next action is user review of the merged collection/export screen after frontend pull/restart. Follow the user's next instruction; no cloud deployment is needed for this UI follow-up.

Recent authorization is frontend UI/UX only. No backend, Lambda, DB, infrastructure, authentication or migration business-rule edits; no source/target/PROD mutation without a newly applicable task. Earlier DEV deployments were authorized historically, not requested now. Do not repeat resolved connector/registry/worker diagnostics without a current symptom. Keep credentials, presigned URLs and tokens out of chat/logs/kit.

## Export feedback fix — 23 October 2026

Latest published feature: **`ba88ea15ac73aea34657ed8316685d2012c1e28e`** — `fix(ui): show export feedback and download beside workspace actions`. User reported the export click appeared to do nothing. The toolbar action previously rendered feedback farther down the page. Progress, errors and export metadata now appear directly in the workspace controls, and successful export adds a green Download export manifest link to the same action toolbar. An incomplete successful response is explicitly reported rather than silently dropping the result. This fixes feedback placement; it does not establish whether the user's live API request succeeded.

Validation: 38 focused artifact-workspace tests, TypeScript and production build passed; actual React preview verified success and download within the toolbar using fixture data. New tests cover pending response, success, API failure and incomplete response in the fixed-scope controls. Backend unchanged. User should pull/restart frontend, create export, then click Download export manifest; live API errors will appear beside the action. User acceptance pending. Broader workflow redesign remains on hold.

