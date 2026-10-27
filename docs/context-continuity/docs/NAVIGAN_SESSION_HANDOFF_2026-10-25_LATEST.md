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

# Navigan session handoff — 25 October 2026 (latest)

## 26 October 2026 — collector parity confirmed; target grants repair prepared

- User created and executed a fresh collector plan at /mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-dev-collector-parity-xubpn5k2/release-plan.json after the older zk9x6g4e plan failed its runtime-signature freshness check. Do not reuse zk9x6g4e.
- User output explicitly confirms DEV repository collector code verified, DEV image rollout completed, PROD/DEV collector artifacts match, DEV settings/roles/schedule retained, no PROD/database commands performed. The helper verifies the actual running task image digest before this success line. No further collector redeploy is indicated.
- Remaining catalog grant gap: navigan_api has SELECT/INSERT on migration_management.migration_target_assessments in DEV but neither in PROD. UPDATE/DELETE are false in both. Existing repository methods SELECT/INSERT this table. Baseline database/bootstrap/roles.sql omitted this table; add it to the existing SELECT,INSERT-only migration evidence grant list.
- Added scripts/repair-target-assessment-grants.py. Default is read-only; --apply restores only SELECT, INSERT on the existing PROD target-assessment table to navigan_api. Exact account/region/Aurora/stack/database/table/role/schema checks; verifies DEV minimum baseline first; transactionally rechecks PROD grants, applies one constant GRANT, verifies, commits and verifies again. Unexpected broad grants or prerequisites stop before writes. Private before/after grant record retained. Idempotent when already correct.
- This changes PROD database permissions deliberately to close the confirmed gap; no application rows, table definitions, DEV permissions, IAM or runtimes are changed. It is not a full database migration or a SAM deployment.
- 98 focused offline checks passed across grant/collector/audit/summary/workspace modules, including read-only default, PROD-only narrow grant, transaction rollback, wrong identity/prerequisite rejection and idempotency. No live grant repair executed here yet.
- Next: user pulls and runs target grant --apply, then confirms output. Follow with local DEV frontend restart/configuration and authenticated summary/migration/discovery/scope/collection/export checks. Until workflow validation is supplied, report verified artifact/configuration parity only. SAM reconciliation follows per user order.


## ECS empty-tags correction — image verified, runtimes not promoted

- User resumed zk9x6g4e plan at e190100. Image copy and content verification passed, then RegisterTaskDefinition rejected tags=[] with "Tags can not be empty." The exception occurred before Lambda code update and ECS service promotion. No candidate task was successfully registered by that rejected call. DEV ECR may now contain the verified copied artifact; preserve/reuse it.
- Fixed task registration to omit the tags argument for empty/absent tag lists, while retaining nonempty existing tags exactly. Task roles, environment, volumes, logging, sidecars and image-verification guards are unchanged.
- 85 focused offline tests passed. New regression cases cover []/None omission; the simulated untagged promotion now rejects any tags argument, matching the live ECS restriction. Tagged task preservation is covered separately.
- Resume the same exact zk9x6g4e --execute plan after pull. Existing revision/config guards continue to protect against changed runtimes; no new build, plan or audit is needed for this request-shape fix.
- Collector promotion, minimum PROD target-assessment grants and workflow validation remain pending. SAM reconciliation stays after parity per user instruction.


## Docker manifest-ID compatibility correction — verified diagnostic evidence

- Retry at cc830d8 resolved the PROD index and pulled its linux/amd64 child, then stopped at the legacy local config-ID equality check. This was before DEV image push, task registration, Lambda code update or ECS service update. Existing zk9x6g4e plan remains runtime-unexecuted.
- User diagnostic confirmed resolved manifest sha256:a4ca0e6ef7ce55a650fd6cc992be48b8195ae398123049fd136f229a63111f21; config digest sha256:1bd0ae681504763c6497ecc23af71b03436225cec657caa805464c6250682661. Docker Id equals the resolved manifest digest, not the config digest. Docker Descriptor identifies the same OCI manifest, RepoDigests includes the exact PROD child reference, and platform is linux/amd64.
- Added verify_local_image: retain classic config-ID verification; additionally recognize a manifest-ID only with exact resolved manifest Id + descriptor digest/mediaType + repository digest reference + linux/amd64 platform. Unrelated identities, absent/conflicting descriptors, index descriptors, wrong references and wrong platforms remain blocked. Destination ECR config and ordered layer digests are still compared with source before any runtime promotion.
- 83 focused tests passed, including integration-style copy coverage for both Docker identity formats and seven negative identity/platform cases. This is offline validation, not a claim of successful cloud promotion.
- Next: pull correction and resume --execute with the exact zk9x6g4e release plan. Do not rerun the whole parity audit or rebuild branch images to address this metadata-format issue. Existing revision/config guards remain enforced.
- Remaining objective/order unchanged: collector promotion, minimum PROD target-assessment grant correction, frontend/workflow validation; then SAM reconciliation.


## Collector image-index correction — no runtime promotion in failed attempt

- User ran collector --apply at ce345cd. Private plan: /mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-dev-collector-parity-zk9x6g4e/release-plan.json.
- Preparation succeeded, then copy_image stopped at the single-platform manifest guard. Failure occurred during initial ECR manifest reads, before Docker copy/push, task registration, Lambda update or ECS service update. No collector promotion occurred.
- Fixed helper to resolve OCI indexes/Docker manifest lists to exactly one baseline linux/amd64 child, ignoring arm64 and unknown-platform attestation entries. Missing/ambiguous matches, unsupported descriptors, mismatched requested digests, cycles and excessive nesting remain blocked.
- Copy now explicitly pulls/tags the verified PROD child digest. DEV destination is also resolved to the verified platform child; returned DEV URI and final running-task digest checks use that child rather than its index digest. Exact config and ordered-layer comparison and identical-duplicate ECR row checks remain enforced.
- 74 focused tests passed, including an integration-style mocked copy that starts from PROD/DEV indexes, verifies pulling only the selected PROD child and returns the DEV child URI, plus missing/ambiguous/cyclic index tests.
- Retry by pulling the correction and --execute of the existing zk9x6g4e plan. Runtime revision/config checks still stop if either environment changed since preparation; do not bypass them or pick an arbitrary latest plan.
- Collector promotion, minimum PROD target-assessment grants, authenticated workflow validation and subsequent SAM reconciliation remain pending. Do not mark parity complete.


## Collector parity promotion prepared / database grant gap identified

- The runtime report pasted as Pasted text(9).txt is truncated at the beginning of DEV's section. Remaining fields were parsed individually, not treated as a complete JSON report. User then supplied the compact extraction from the original local MWbpd6 report: DEV errors=[], PROD errors=[]; the only catalog difference is navigan_api privileges on migration_management.migration_target_assessments.
- DEV has SELECT/INSERT=true and UPDATE/DELETE=false. PROD has all four=false. Repository.get_target_assessment SELECTs and save_target_assessment INSERTs this table; preserve DEV grants. PROD needs a separately scoped minimum grant correction to close this parity gap; do not revoke working DEV access or claim an observed production outage solely from this group-role check.
- Runtime evidence: workspace ownership/public access/versioning/KMS controls match; repository workers Active/Successful with enabled one-minute schedules targeting the right worker; image services COMPLETED 1/1; all worker DB/secret/workspace bindings match their own environment.
- Image entrypoint, requirements and every installed Python package METADATA hash match across DEV/PROD. Application source differs in both repository collector ZIPs and image collector contents. Do not infer equal code from healthy services or equal dependency metadata.
- Image collector IAM documents match after substituting environment-specific bucket/KMS resources, including the same explicit source registry role. Migration API/repository role policy names/legacy duplicate grants differ; DEV has a legacy 000000000000 placeholder statement plus separate actual-role grants. Preserve functioning grants; reconcile template/ownership later with SAM. PROD extra legacy recovery-bucket policy is historical, not a requirement to create/copy another DEV bucket.
- Added scripts/align-dev-collectors-with-prod.py: default/--prepare reads only and saves original DEV ZIP/task plus an exact runtime plan; --apply prepares and executes; --execute accepts a specific saved plan. Copies the currently deployed PROD repository collector ZIP into DEV Lambda, without rebuilding branch source or copying PROD configuration. Copies the digest-pinned deployed PROD image into the existing DEV ECR repository, verifies exact config/ordered layer digests, registers a copy of the current DEV task changing only the collector image, then promotes only the DEV service. DEV roles/volumes/logging/env/sidecars/schedule retained.
- Guards: exact account/parents/databases/worker identities, stable one-task services, revision/config checks, checksum-verified ZIPs, identical duplicate ECR rows only, single-platform linux/amd64 image validation, immutable candidate/rollback records, completed ECS rollout and actual running task digest verification. Concurrent runtime changes stop promotion. It does not change IAM, schema, source agents or PROD. It does not start an explicit collection job.
- 66 focused offline checks passed, including simulated execution proving DEV-only Lambda/task/service writes and preserved DEV role/env/sidecar settings. No live collector promotion performed here yet.
- Next: user pulls and runs collector parity --apply with Docker available and existing TMPDIR; obtain exact completion/rollback output. Then handle the confirmed PROD target-assessment grant gap through a minimal controlled correction, validate local DEV frontend/API routing and real collection/export behavior. SAM reconciliation follows parity per user instruction.


## DEV migration correction confirmed / consolidated remaining checks

- User ran align-dev-workspace-with-prod.py --apply at 66867fb. Output explicitly confirmed the one-file DEV correction deployed, package checksum verified, migration module source matched the reviewed PROD baseline and DEV configuration stayed unchanged. Exact rollback/release plan: /mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-dev-workspace-parity-p_2julqf/release-plan.json.
- No further migration API redeployment is indicated by this output. Do not run the broader legacy helper again to verify parity; its current branch source would reintroduce the newer workspace behavior.
- Added scripts/audit-parity-runtime-details.py to collect the remaining evidence in one read-only run: repository-worker sources/schedule/bindings, image service bindings/role, workspace storage controls, API/collector IAM policies/trust, and catalog table columns/constraints/indexes/RLS policies/navigan_api table privileges.
- Optional --inspect-images uses local Docker with private temporary ECR authentication, pulls only trusted digest-pinned Navigan images, creates an unstarted container, copies application source/entrypoint/requirements and installed package METADATA for comparison, then removes its own container/credential directory. It never executes image entrypoints or starts collection jobs. Pulled images may remain cached locally.
- JSON output contains policy ARNs/conditions and schema metadata, not application records, secret values or Lambda download URLs. Errors are explicit and parity remains UNVERIFIED. No cloud update APIs, DDL or business writes are used.
- Limits: table catalog/grants are not every database object/sequence/function grant; IAM policy inventory requires semantic review/effective-access checks; image metadata/source comparison is not a complete OS/native dependency audit or successful job evidence. Authenticated local DEV frontend/workflow verification remains required.
- 55 focused offline tests passed across audit/summary/workspace correction modules. The new consolidated audit has not run against live AWS yet. User should pull and run --inspect-images with Docker available, then upload the JSON report.
- Continue DEV–PROD parity first. SAM method/template reconciliation remains explicitly deferred by user until parity is validated.


## DEV parity follow-up — second live inventory and packaging correction

User explicitly ordered: finish DEV–PROD parity first, then reconcile the SAM deployment method. Do not start SAM changes yet.

- User execution output confirms all three DEV summary routes/packages deployed and verified using the hf5p046v release plan.
- User execution output confirms DEV MigrationFunction updated through the legacy --migration-only --apply helper; rollback record: /mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-source-connection-dev-7w4sdsgf.
- Second inventory at 2026-10-25T17:24:56.013091+00:00, checkout f79de2b: both inventory error lists empty. DEV has 134 routes, PROD 133; no PROD-only routes; the sole DEV extra is connector upgrade. All common route auth metadata matches.
- Four previously differing MigrationFunction source files now match PROD. However DEV artifact_workspace.py became the newer committed c42fb1d version (SHA-256 8eae340425badf85f7cc537b57b30c28d59d4b94954a0f1659c8abb823f89bdb). PROD still runs the prior reviewed file (SHA-256 1cd70fe6275537bcbd5c7719ee496c3ade6c9a3f90bcab6d45476d2c75d14e81). Both hashes independently matched the respective GitHub versions.
- The newer file lazily imports workspace_reuse.py during workspace creation; that module is absent from both deployed ZIP inventories. The old DEV helper omitted it. This is a packaging defect introduced into DEV by the advised sync command, not proof of an observed user-facing exception. Correct it promptly.
- Added scripts/align-dev-workspace-with-prod.py: exact reviewed PROD/DEV source hashes, all other migration Python files must already match; replace only artifact_workspace.py in DEV's current ZIP, remove its stale bytecode, preserve every unrelated member and DEV configuration. AWS reads-only by default/--prepare; --apply prepares and executes the same one-file correction; --execute PLAN supports an exact private plan. Identity/revision/package/config checks guard the update; private rollback retained. No PROD, schema, IAM, source-agent, collector or storage mutations.
- Fixed the legacy DEV helper to bundle workspace_reuse.py as an additive module on future deployments. Do not rerun that broader helper simply to apply this correction: it would install the newer branch workspace behavior again. SAM reconciliation must later capture the selected baseline and all dependencies.
- 45 focused offline tests passed, including a simulated execute proving exactly one DEV Lambda code write and preserved environment. Live correction execution remains pending.
- PROD frontend remains revision 23 with desired/running 1/1 and rollout COMPLETED. Both image worker services remain 1/1, but source/configuration parity is not established by service health or differing image digests.
- Remaining after correction: repository/image collector code and runtime/dependency comparison; schema/grants, IAM/trust and storage/configuration checks; local DEV frontend restart and authenticated migration/collection/export smoke checks. No full parity claim is justified yet.


## DEV parity findings — uploaded live inventory, 25 October 2026

This observation supersedes earlier revision-23-unconfirmed notes below.

- User inventory observed at `2026-10-25T16:55:34.062993+00:00`, checkout `03f1980`. Both DEV and PROD inventory error lists are empty.
- PROD frontend is now confirmed task revision **23**, desired/running 1/1, pending 0, rollout COMPLETED, image digest `sha256:bab279913816fed2e113f8e4cb94187bbeeb835f0781896eb0959c25a55047f6`. This proves task-definition/service state, not authenticated browser acceptance.
- DEV API has 131 routes; PROD 133. PROD alone has GET customer/environment/cluster summary routes. DEV alone has POST /api/v1/clusters/{clusterId}/connector/upgrade. Common route auth metadata matches in this inventory; exact integration targets still require verification. Preserve DEV's extra route.
- DEV MigrationFunction differs from PROD in four own-module files: repository.py, service.py, source_authentication.py, source_connector_installation.py. Each PROD file hash exactly matches the current branch source read at `03f1980`. Existing `deploy-source-connection-screen-dev.py --migration-only` is the established scoped DEV path; inspect preparation before --apply. No source agent reinstall is needed to update API code.
- Lambda package-wide differences include unrelated bundled modules. Do not treat every different bundled file as an active function regression or copy whole PROD ZIPs blindly. DEV's shared/access.py matches current branch and both current MigrationFunction packages; several older PROD packages contain a different helper. Preserve current DEV access behavior pending semantic review.
- Both image services are COMPLETED with desired/running 1/1. DEV and PROD image digests differ; digest inequality alone does not establish which collector code differs. Repository worker packages differ too. Worker source/dependency comparison and schema/grants/IAM/storage checks remain pending.
- DEV nested Access/Cluster/Customer/Environment stacks report UPDATE_ROLLBACK_COMPLETE. This is historical stable rollback state, not proof of a current failing deployment; inspect scoped change sets rather than deploy the whole parent.
- Added `scripts/deploy-summary-apis-dev.py`, using the tested summary-only release logic with exact DEV parent/database/workspace/plan format. Default reads only; --prepare uploads versioned artifacts to DEV workspace and creates an UNEXECUTED scoped nested change set; --execute accepts only its DEV plan and verifies resource scope/revisions. PROD release script is unchanged.
- Shared PROD/DEV summary tests plus DEV-boundary and audit tests: **35 passed**. No AWS release executed here.
- Next: user pulls current branch and runs DEV summary --prepare; obtain actual printed plan path for execution. Then reconcile DEV MigrationFunction through established scoped DEV helper, assess workers/configuration and schema/grants, restart the WSL frontend on current source, rerun inventory and perform authenticated Dev/Prod smoke checks. Do not declare parity yet.


This is the current checkpoint. It supersedes older current-status sections where they conflict; retain older entries as history.

## Repository and working rules

- Repository: https://github.com/shankamal/Navigan
- Active branch: `new_migration_approach_18oct26`.
- User checkout: `/mnt/b/Langchain_Ai/Navigan-migration-test`.
- AWS profile `navigan`, region `ap-south-1`, account `905418045935`.
- User works from WSL and has no direct cluster terminal/network access established. Do not assume laptop kubectl can reach a private EKS endpoint.
- Before changes, check branch, status and recent commits. Preserve user files and unrelated modifications; no reset, clean or extra worktree.
- Keep fixes scoped and progress updates concise. Do not request approval repeatedly for already-authorized work.
- Primary migration objective remains collecting source definitions and exact container image content into private S3, then export and target validation. Broad UI consistency work remains deferred to final stabilization.
- Shared physical connector / authorized customer association requirements in older notes remain unresolved unless separately proven. Do not treat the older source-scoped installer fix as that implementation.

## Accepted login design

User accepted the design after commit `1a7fab6492c5aa0c48676f5f85b87e7af5b39e28`, then explicitly requested compact controls and a slightly narrower right panel in `6916e119a6445e7b6b1526514e79a42e4d3b19d5`.

- Charcoal Deloitte title bar; light left story area; charcoal right sign-in area.
- Coloured Indian king at a ship helm and harbour illustration retained. Do not revert to grayscale king.
- No left Navigan logo/name block. One reverse Navigan mark sits beside **Welcome to Navigan** on the right.
- Exact left headline on two lines: **Navigate your cloud.** / **Simplify your operations.**
- Supporting line: **Manage with confidence. Migrate with clarity.**
- First headline line uses lighter charcoal type, second deep green with more separation; supporting text is smaller and normal, no longer italic.
- Sign-in subtitle: **Sign in to your workspace.**
- Sign in button is Deloitte green `#86BC25`, with dark readable text. The user's latest request supersedes earlier deep-green button preferences for this login button.
- Small provider logos; AWS logo only, with no repeated AWS text label.
- Latest desktop split: 64% story / 36% dark panel; form max-width 360px; desktop input and primary button height 40px. Narrow two-column layout uses 55/45; mobile input/button heights remain 48px/44px.
- No scroll on normal login at the checked viewport sizes. Do not hide scrollbars to conceal inaccessible content; expanded auth challenges/errors must remain accessible.
- Auth/Cognito behavior was preserved. 14 focused login/auth-entry tests passed after branding changes. Actual-component browser fixtures verified desktop/mobile layout; latest compact CSS checked at 1536x696 and 1024x600 with matching document/client dimensions. These are fixture checks, not proof of live authenticated sign-in.

Relevant files:
`frontend/src/shared/auth/sign-in-screen.tsx`,
`frontend/src/shared/auth/login-form.tsx`,
`frontend/src/shared/auth/login-workspace.css`,
`frontend/src/shared/components/navigan-mark.tsx`,
`frontend/public/graphics/navigan-royal-harbour.webp`.

## Frontend deployment status: distinguish deployed from prepared

Frontend ECS cluster: `navigan-frontend-Cluster-bw32Pkwxn8Cs`.
Service: `navigan-frontend-Service-vMtHq9h7A9mz`.
Task family: `navigan-frontend-TaskDefinition-j9W80aX9PBkf`.

- **Last confirmed deployed: revision 22.** User's ECS output showed PRIMARY / COMPLETED, desired 1, running 1, pending 0. No rollback.
- The execute helper initially raised “Service did not retain the requested revision” before the later ECS observation confirmed completion. Do not redeploy solely because of that earlier message. Exact timing cause was not independently established; helper's final running-image and HTTP checks were not reached.
- Revision 22 image: `905418045935.dkr.ecr.ap-south-1.amazonaws.com/navigan/frontend@sha256:5931ba5db8970e0977bab80524547ab202d4158eb8f07cd6f16df67e633e786a`.
- **Latest prepared candidate: revision 23**, containing compact-controls change `6916e11`.
- Revision 23 image: `905418045935.dkr.ecr.ap-south-1.amazonaws.com/navigan/frontend@sha256:bab279913816fed2e113f8e4cb94187bbeeb835f0781896eb0959c25a55047f6`.
- Revision 23 release plan: `/mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-prod-frontend-zg_c5ip6/release-plan.json`.
- Exact execute command was supplied, but **no execution result for revision 23 has been received**. Verify live state rather than claiming it deployed.
- Deploy helper: `scripts/deploy-frontend-prod.py`. Build/register with --prepare; promote only via --execute and its actual newly printed plan path. Never give a literal placeholder as a runnable command or select an arbitrary latest temporary plan.
- Python: `/mnt/b/Langchain_Ai/navigan-deploy-venv/bin/python`; TMPDIR: `/mnt/b/Langchain_Ai/navigan-deploy-tmp`.
- Backend readiness requires the shared Aurora cluster `aws-infra-platform-db` to be available; a stopped DB caused one prepare to stop before deployment.

### ECR verification correction

Commit `d148e62c65e19b0b76d83b2ea440e6a5901bbe3e` fixes identical duplicate ECR manifest rows. User diagnostic showed two rows for one requested digest with no failures. Helper accepts duplicates only when digest, manifest text and media type agree; missing/conflicting manifests remain blocked. Linux/amd64 selection retained. **33 offline deployment tests passed.** Fix is already on this branch; do not repeat it or weaken verification.

## UI data performance work already completed

- Three production summary routes (customers, environments, clusters) were deployed and verified present through `scripts/deploy-summary-apis-prod.py` at `62d4b6c`.
- User network evidence then showed summary 200 responses around 420–434ms, regular lists around 397–437ms, and no previous burst of 28 fallback count requests. This does not prove all full-page load latency resolved.
- Frontend `d5a70bc` split sign-in presentation into a dynamic import, separated migration create-page imports, and added intent-based prefetch. Later login releases preserve these changes. Do not reintroduce eager auth presentation or migration barrel imports.

## Cluster tools incident — resolved without a code change

- User reported recurring disabled Headlamp, Argo CD, Prometheus and Grafana buttons after daily node shutdown/startup.
- Initial screenshot: several components showed Healthy, but launch access said cluster had not connected to shared tools gateway; Argo CD showed Missing.
- AWS screenshot identified EKS cluster **dbs-sims-clus2**, node group **dbs-sims-clus2-system-ng**, **desired size 0**, and no Fargate profiles.
- After restoring worker capacity, user explicitly confirmed **all healthy and buttons enabled**. Recovery occurred without connector reinstall, gateway redeploy or code changes for this incident.
- Do not reopen this as an active tunnel outage unless new symptoms appear. Enabled buttons alone do not prove each tool's browser launch was tested.
- Code read during investigation: cluster connector automatically retries its tools tunnel; chart selects nodes labelled `navigan.io/platform-services=true`. No replacement-node label defect was proven.
- **Remaining follow-up, deferred:** stale health/status presentation. Navigan displayed Healthy while worker capacity was zero. Distinguish freshness, component health and tool access readiness; do not claim a stale-health fix has been implemented.
- No cluster, gateway, IAM or source-agent mutation was performed by the assistant during this investigation. Do not reinstall tools or modify gateway security based on the old screenshot.

## Next session

1. Read this handoff first, then inspect branch/status and any newer user output.
2. Confirm whether revision 23 was executed, using existing user evidence or read-only ECS status.
3. Preserve the accepted login design; no further redesign is requested.
4. Cluster tools incident is resolved. Stale health reporting and broad UI consistency remain deferred; continue only the next user-directed task.

## DEV parity restoration — new authorized task

User requested restoring all recent PROD implementations/fixes to DEV and verifying parity. This supersedes the previous wait-for-requirement next action, while broader UI redesign stays deferred.

- Repository code is shared on `new_migration_approach_18oct26`; latest inspected starting HEAD was `c508926`. Runtime parity has NOT been established.
- Added `scripts/audit-dev-prod-parity.py`: AWS read-only inventory for DEV `navigan-ashok-dev` and PROD `navigan-custmanagement-cfnstk`, nested Lambda/application source hashes, route/auth inventory, dedicated collector stacks and ECS task references. Optional `--include-source` downloads ZIPs only into memory and verifies package checksums before hashing application Python files. No cloud writes, secret retrieval, database data copy or source-agent mutation.
- Six offline tests passed. No live AWS run: agent has no user WSL checkout/AWS session. User must run the audit through existing profile `navigan` before selecting scoped DEV updates. Inventory errors remain explicit; report always says parity UNVERIFIED.
- This initial audit does not compare database schemas/grants, IAM/trust policy semantics, storage configuration or exact route target mappings. These checks plus authenticated workflow validation are required before declaring parity. DEV frontend is still local WSL unless fresh user evidence establishes a hosted DEV runtime.
- Preserve DEV database `navigan_dev`, DEV endpoints, storage, connector/customer associations and environment-specific identities. PROD database remains `navigan`. Do not copy PROD records/tokens/config wholesale into DEV or run PROD-only deploy scripts against DEV.
- Candidate recent gaps: migration API/source lifecycle fixes, customer/environment/cluster summary APIs, worker source/runtime and schedules, accepted login and lazy-loading/performance UI changes. Derive actual changes from live inventory rather than redeploying all components.
- Revision 23 remains deployment-unconfirmed until fresh ECS evidence. No DEV or PROD runtime changed during this preparation.
