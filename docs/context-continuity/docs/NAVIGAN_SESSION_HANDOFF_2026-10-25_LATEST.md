# Navigan session handoff — 25 October 2026 (latest)

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
