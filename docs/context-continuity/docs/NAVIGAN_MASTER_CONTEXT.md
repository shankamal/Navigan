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

## Export feedback fix — 23 October 2026

Latest published feature: **`ba88ea15ac73aea34657ed8316685d2012c1e28e`** — `fix(ui): show export feedback and download beside workspace actions`. User reported the export click appeared to do nothing. The toolbar action previously rendered feedback farther down the page. Progress, errors and export metadata now appear directly in the workspace controls, and successful export adds a green Download export manifest link to the same action toolbar. An incomplete successful response is explicitly reported rather than silently dropping the result. This fixes feedback placement; it does not establish whether the user's live API request succeeded.

Validation: 38 focused artifact-workspace tests, TypeScript and production build passed; actual React preview verified success and download within the toolbar using fixture data. New tests cover pending response, success, API failure and incomplete response in the fixed-scope controls. Backend unchanged. User should pull/restart frontend, create export, then click Download export manifest; live API errors will appear beside the action. User acceptance pending. Broader workflow redesign remains on hold.

# Current collection follow-up — 23 October 2026

## Latest follow-up — merged collection and export (23 October 2026)

Published feature commit: **`bc87adf74c6eaf394db22db43cb17ce258adcce7`** — `fix(ui): combine artifact collection and export with named copy progress`. This narrowly scoped Files & images request supersedes the earlier three-stage preparation UI; it does not resume the broader migration workflow redesign, which remains on hold. User acceptance of this follow-up is pending; Migration Overview remains the accepted visual reference.

- Saved-scope Files & images now has **Check sources → Collect & export**. Review/export is no longer a third navigation destination.
- Create workspace, Refresh workspaces, repository collection, image collection and export are grouped in one toolbar. Existing scope/stale/permission/readiness guards and explicit POST actions are unchanged; a current matching workspace still disables creation.
- The anonymous “succeeded · Attempt 1” job list is removed. The shared artifact table identifies actual files/images, GitHub repository / container registry / source-cluster live-export or Helm origins, and progress/status matched through the existing API's artifactId.
- Saved rows show 100%; active copies use an indeterminate animation because the API does not report bytes transferred. Queued, failed/retry, verifying and source-action states are explicit. Overall percent is based on required artifacts saved to S3, excluding historical runs; incomplete work never rounds up to 100%.
- All / Remaining / Saved-excluded filters use the same table. Export remains available in this view and exact S3 metadata retains the existing export-response limitation.
- Read-only progress polling runs every five seconds only for active visible pending work, without reloading the page or automatically starting collection/export. It stops on completion, leaving the stage, unmount or read failure. Manual refresh remains available.
- Validation: **73 focused tests**, TypeScript and production build passed. Tests cover job-to-artifact identity mapping, honest indeterminate progress, one toolbar, polling completion/inactive cleanup and merged navigation. Browser fixture checks covered queued/running/failed/saved rows, creation disabled/export enabled after completion, and no page-wide overflow at 390/768/1024/1280/1440/1920px. This is not live AWS validation or a whole-suite pass.
- No backend/API payload, Lambda, database, infrastructure, authentication or migration scope/business-rule changes. Pull/restart the frontend for user review; no AWS redeployment is needed for this UI release.

---

# Earlier 23 October override — superseded where the collection follow-up differs

Read `docs/NAVIGAN_SESSION_HANDOFF_2026-10-23_LATEST.md` first. This override supersedes older current-state labels, blockers, branch references and next-task instructions below.

Active user branch: `new_migration_approach_18oct26`; verified published feature HEAD: **`8236e58505d148f72c349640ccde3f1cf30d4cfd`**. Latest accepted UI baseline is Migration Overview (user: “much better”): Graphite/charcoal, shared Geist typography, compact spacing, colored donut charts/provider icons, green actions and one attention queue. Preserve accepted shared PageHeading offset fix `cfbfbaae7`.

Since the 20 October checkpoint, DEV S3 artifact workspaces, collection workers, recovery and final export progressed to user-reported success: all 12 shown jobs succeeded and an export with 14 collected artifacts / 2 historical exclusions downloaded. This does not establish target deployment readiness. Source discovery and scope/artifact preparation are now separated; source connection setup remains in new migration creation. Files & images uses Check sources → Collect artifacts → Review & export at `125cecb4`, with duplicate creation protection for the current saved scope. Exact S3 object paths are in the export manifest; the UI can show the shared folder after export because current workspace read responses omit persistent storage metadata.

**Explicitly deferred:** the user wants major further improvement to the full migration workflow but has put it on hold. Do not resume that redesign without a new instruction. Current task is this kit refresh, then follow the user's chosen task. Recent work is frontend-only: do not alter backend APIs/Lambda/database/infrastructure/authentication or migration business rules under this authorization. No PROD deployment, target workload migration or traffic cutover was done. Do not repeat historical source-ID, HOME or writable-temp diagnostics without current evidence.

Use the user's existing WSL checkout `/mnt/b/Langchain_Ai/Navigan-migration-test`. Preserve local files; no reset/clean/deletion/new worktree. The agent sandbox's local master history differs from published remote history; never push its full tree as the user branch. See the latest handoff for release IDs, tests, runtime evidence, constraints and safe startup commands.

---

## Historical master context — retained for reference, superseded where it differs

# Current recovery override — 20 October 2026, 01:15 IST

Read `docs/NAVIGAN_SESSION_HANDOFF_2026-10-20_0115_IST.md` first. This override supersedes earlier current-state labels below. Active DEV branch: `new_migration_approach_18oct26`; latest published UI commit: **`2cfb422`**. User-reported source discovery/assessment completed; registry images became Available. Earlier source-ID mismatch and HTTP 400 volumeClaimTemplateNames incidents are historical/resolved at the user's acceptance checkpoint, not today's first task. Retailflow source ECR mirroring and source rollouts passed; target unchanged. Last user-confirmed backend/connector upgrade: **`69a61b4`**. Latest approved table/drawer redesign is implemented/pushed and requires frontend pull/refresh only, with 53 focused tests/TypeScript/build passed. Live user confirmation of the final UI commit is still pending. No PROD deployment or target migration was performed.

**Next-session priority:** explain and improve the presentation of the user's latest totals—8 namespaces, 35 workload controllers, 479 resources, 438 source findings—using a current readonly inventory/finding breakdown. Do not equate findings with failures or controllers with applications. Do not silently exclude platform namespaces or narrow discovery to Retailflow; group evidence for viewing and preserve raw detail. No grouping/label change has yet been implemented. Use the latest handoff for boundaries, exact release evidence, known limitations and history. Avoid repeated diagnostic steps and speculative connector reinstalls.

---

## Preserved historical master context (older overrides below are historical)

# Navigan — Master Context & Daily Recovery Prompt

> **CURRENT OVERRIDE — updated 19 October 2026, last runtime evidence 18 October:** Read `docs/NAVIGAN_SESSION_HANDOFF_2026-10-18_EOD.md` first. Active DEV branch is `new_migration_approach_18oct26`, last pushed/user-pulled and DEV-deployed commit `428cd3b`. Source connection Option 4, draft editing, stable progress, source-first discovery and source-only assessment support are implemented. Real DB Schenker discovery is **blocked by a source-registration mismatch**, not completed. The healthy live connector serves `SRC-ae85e62d759d47fabf8eb87610ea39b9`; assessment `MIG-9beaa527a0754613aa1d8e7a7ee6a8af` waits for `SRC-2f0e434335e04ef0bdccd74cb3322f2c`. First verify ownership/associations; no speculative reinstall/reassignment. DB Schenker and JPMC are real approved customers; others are demo. Cross-customer shared-cluster access is still unimplemented. No PROD deployment in this increment. Older connector-change exclusions below describe earlier release scopes; the two DEV migration Lambdas were explicitly updated on 18 October, without blanket authority for further infrastructure changes.

## Historical baseline and prior overrides (superseded where the current handoff differs)

> **Latest state override (2026-10-17 EOD IST):** Read `docs/NAVIGAN_SESSION_HANDOFF_2026-10-17_EOD.md` before acting. Today we reviewed the architect's application-centric migration ideation and delivered a detailed 67-row code gap tracker. The Source UI working branch is `codex/migration-source-ui-compact-topology` (remote HEAD to be freshly checked). **Last user-confirmed** production frontend was ECS task `:8` from commit `84ea9ee`, with completed deployment and HTTP 200 on `/login`; this was not rechecked live tonight. Previous `:6`, `:5`, `0179edb` as latest, and `codex/migration-intelligent-planning` as active are historical. This master file retains earlier baseline snapshots below.
**Baseline:** 16 October 2026 | **Version:** 1.0 | **Status:** Working reference; verify live state before changing infrastructure

> Copy the complete section below into a fresh ChatGPT session at the start of each day. Treat it as the project baseline, not as evidence that every feature is implemented or every deployment is current.

## ROLE AND OPERATING CONTRACT
You are my principal solution architect, senior full-stack engineer, DevSecOps lead, and controlled-release advisor for **Navigan**, a Deloitte-styled, API-driven, multi-cloud Container Management Platform. Maintain continuity. Do not change development architecture, worktree, deployment strategy, feature scope, or code paths without explaining the reason and obtaining approval. Work in small, verifiable changes; favor one consolidated command and a clear pass/fail result over long sequences of exploratory commands. Avoid repetitive investigation and unnecessary rebuilds. Separate facts into **VERIFIED**, **INTENDED/DESIGNED**, **IN PROGRESS**, **UNKNOWN**, and **OUT OF SCOPE**. Never represent an intended feature as deployed.

At the beginning of each session: (1) acknowledge this baseline; (2) ask what task to continue only if not provided; (3) read the most recent session checkpoint; (4) perform only the minimum read-only checks relevant to that task; (5) state the exact repo/branch, DEV or PROD target, affected components, acceptance criteria, rollback, and exclusions before any mutation. Do not perform or recommend infrastructure changes in production on assumptions alone. Do not invent results of commands you cannot execute.

## 1. PRODUCT OBJECTIVE AND BOUNDARIES
Navigan is a multi-tenant, role-controlled, API-first Container Management Platform/command center. Its product pillars are Customer Management, Environment Management, Cluster Management, Migration Intelligence / Planning, platform setup/onboarding, dashboards, and governance. Its intended provider coverage includes AWS, Azure, GCP, OCI, OTHER, Kubernetes/OpenShift; capabilities differ by module and must be confirmed in code. It follows Deloitte-inspired branding, restrained green highlights, elegant typography, high information density, actionable status, uncluttered professional UI. Avoid unnecessary rounded cards, UI redesigns, and decorative architecture at the expense of working functions.

Core flow: Customer Onboarding → Platform Setup / New Cluster Setup → Review & Submit; governance as applicable: Business Owner → Security → CloudOps → Final Approver. “Platform Setup Request” was to become “New Cluster Setup”; Environment navigation should include “Create Environment.” Capture cluster counts, worker node groups, worker node quantities and sizing in the **cluster setup** workflow, not a premature generic platform form. Existing behavior takes precedence over draft nomenclature; verify before UI modifications.

Scope is control-plane management and planning, not automatic deployment of workload migration or unauthorized external-cluster manipulation.

## 2. VERIFIED/KNOWN DEV AND PROD ENVIRONMENTS
| Dimension | Development (DEV) | Production (PROD) | Confidence/Notes |
|---|---|---|---|
| User-facing frontend | Local WSL/Windows laptop, Next.js at `http://localhost:3000` | `https://navigan.click` on AWS ECS/Fargate | Verified |
| Main local repository | `/mnt/b/Langchain_Ai/Navigan-migration-test` | Release prepared in `/mnt/b/Langchain_Ai/Navigan-prod-release`; frontend runs on ECS | Verified paths at last session |
| GitHub | `https://github.com/shankamal/Navigan` | Same source repository, separately controlled release | Verified |
| DEV feature branch | `codex/migration-intelligent-planning` used for current Migration Planning workspace | PROD image built from isolated migration staging worktree; DO NOT assume `release/migration-review-export-20261016` includes feature | Verified from branch/file comparison |
| Branch pitfall | `release/migration-review-export-20261016` at `fc3ab46` lacked `planning-workspace.tsx` and `/plan` route, so local DEV button disappeared | Do not change production to fix a local checkout | Verified |
| Staging worktree | Separate `release/migration-review-export-staging` checkout | Isolated source used for release | Verified; validate actual branch/commit before new release |
| AWS profile / region / account | `navigan` / `ap-south-1` / `905418045935` for known AWS resources; DEV backend utilizes AWS | Same named account/profile/region for documented resources | Verify permissions and target on each operation |
| DEV stack | `navigan-ashok-dev` was recorded as `UPDATE_COMPLETE` on 14 Oct | N/A | Historical snapshot only |
| Frontend ECS cluster | Local frontend, not production ECS | `navigan-frontend-Cluster-bw32Pkwxn8Cs` | Verified |
| Frontend ECS service | Local Next.js | `navigan-frontend-Service-vMtHq9h7A9mz` | Verified |
| Frontend task family | Local process | `navigan-frontend-TaskDefinition-j9W80aX9PBkf` | Verified |
| Current production task revision | N/A | `:5`, ECS rollout `COMPLETED`, 1/1 running on 16 Oct 2026 | Verified at that time; check before subsequent changes |
| Production ECR | N/A unless explicitly used for DEV images | `905418045935.dkr.ecr.ap-south-1.amazonaws.com/navigan/frontend` | Verified |
| Production frontend image | N/A | Immutable digest `sha256:6bc86cc7a37a933a4d144ccdc64d5f24281e1c2b4c5a2ee620242be82542baa8`, tag `migration-review-export-20261016-authfix` | Verified |
| Previous frontend | N/A | Previous task `:3`, previous ECR image digest `sha256:d770c588d845430c0803469948a29087657c5623b6ccde84bdb0467e879c9994` | Historical fallback; does not guarantee working authentication |
| Production migration SAM stack | DEV backend-specific stack subject to verification | `navigan-custmanagement-cfnstk`; migration-only nested stack updated | Verified release snapshot |
| Migration API Lambda | DEV function name must be discovered read-only | `navigan-custmanagement-cfnstk-Mi-MigrationFunction-nYtXL48n5mkD` | Verified release snapshot |
| Production DB | DEV DB specifics not sufficiently verified | Aurora/RDS Data API cluster `aws-infra-platform-db`, logical DB `navigan` | Verified release context |
| Cognito issuer | Development frontend `.env.local` contained prod issuer during auth fix; do not assume that is suitable for all future DEV testing | `https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_PD9mv4fkd` | Verified PROD issuer |
| Cognito app client | Read-only compare with actual DEV config | `aa7v5laqu1mkqamt7ao51u7ms` | Verified production client |
| PROD DB migrations | Avoid applying to wrong DB | `025_migration_planning_drafts.sql`, `026_migration_target_assessments.sql` applied and committed on 16 Oct | Verified |
| DEV containers and DB | Frontend local; backend via AWS API Gateway/Lambda + RDS as previously used | Frontend Fargate + API Gateway/Lambda + Aurora | Frontend/prod known; DEV endpoint identifiers must be confirmed |

**Never expose secrets, auth codes, tokens, cookies, or private credentials in logs or chat.** AWS resource names here are reference identifiers, not blanket permission to modify them.

## 3. CUSTOMER MANAGEMENT
Functional specification: customer CRUD/onboarding, provider association, lifecycle `DRAFT → ACTIVE / DEACTIVATED`, multi-tenant separation, customer metadata/ownership, request visibility, review/submit, status tracking, audit trail and role-aware operations. Provider enumeration in recorded Customer Management spec: `AWS`, `AZURE`, `GCP`, `OCI`, `OTHER`. Prior specification included user stories `US-CM-001` through `US-CM-014`; **retrieve the actual approved user-story document before claiming exact acceptance criteria**. Do not infer completed features solely from this scope. Customer isolation, tenant authorization, and consistent API/database contracts are mandatory.

## 4. ENVIRONMENT MANAGEMENT
Manage environments owned by customers, including create/list/details/update, environment-to-customer relationships, cloud-provider/account/subscription context, region, classification, lifecycle, ownership, approvals, dependencies and linked clusters. Sidebar should provide **Environment Management → Create Environment**. Scope should account for DEV/IST, UAT, hotfix, performance, CAT, production where applicable; these are examples of lifecycle/deployment environments and should not be hard-coded as universal provider types. Distinguish Navigan's own **DEV/PROD application deployments** from **customer environments managed within Navigan**. Confirm actual attributes, approval workflow, edit restrictions and deployed functionality against code/schema.

## 5. CLUSTER MANAGEMENT / NEW CLUSTER SETUP
Manage Kubernetes, AWS EKS/ECS, Azure AKS, OpenShift and other supported cluster integrations; inventory, cluster metadata, node/node group inventory, health, namespaces, workloads, dependency visualization, status, topology, cluster-to-environment mapping and permissions. For new cluster requests capture number of clusters, target environment, cloud account, VPC/network/subnets as relevant, Kubernetes version, node groups, worker-node count, instance type and capacity, access model, regions/zones, addons/storage/observability/security, review/approval, Terraform/IaC handoff. Separate existing cluster discovery/registration from provisioning. Provider support and actual provisioning capability must be confirmed individually. No automatic changes to customer clusters without an approved implementation path.

## 6. MIGRATION INTELLIGENCE — CURRENT PRIORITY
**Only assessment and planning; no migration execution.** Intended end-to-end steps: **Source → Target → Compatibility → Remediation → Plan → Review & Export**. API-driven like other Navigan capabilities, with frontend rendering backend results. Source examples: self-managed Kubernetes `navigan-migration-lab` (3 Ready nodes, Kubernetes v1.37.1, 8 namespaces recorded in assessment screenshot), target EKS `DEV2-CLUS2-DEMO`. Screenshot migration `MIG-37e3fb60b40244fba74f6e8b86289ab9` was APPROVED, 163 resources assessed, 76% compatibility, 64 remediation, 7 automated, 0 critical, 163 mapped; snapshot only, not universal truth.

Capabilities planned/built across active branch: source inventory discovery; namespace/workload/resource/dependency selection; Kubernetes mapping and topology; readiness/capacity checks; target EKS assessment; StorageClass/CSI and PVC considerations; compatibility scoring and findings; remediation recommendations and handoff; draft selection/save/reopen; plan preview; review/export. Verify individual capabilities and the live API/DB paths with tests before declaring end-to-end success. Historical source inventory had **163 resources but zero dependencyReferences** in one result; preserve captured evidence and fix mapping at the responsible layer rather than guessing dependencies. Source/target inventories must remain separate and clearly labeled.

Confirmed release API additions in migration-management scope:
- `GET /api/v1/migrations/{migrationId}/target-assessment`
- `POST /api/v1/migrations/{migrationId}/target-assessment`
- `GET /api/v1/migrations/{migrationId}/target-compatibility`
Other migration endpoints exist but are **not enumerated here**: discover actual API Gateway/SAM/backend route registrations and OpenAPI/handlers before generating a definitive endpoint inventory. Avoid inventing endpoints or assuming the frontend is the source of truth. `planning_draft` backend validation must remain aligned with Pydantic v2 schema, handler model validation/dump, service and database column.

The entry route found on the intelligent-planning branch is `frontend/src/app/(workspace)/migrations/[migrationId]/plan/page.tsx`; UI file `frontend/src/modules/migration-management/planning-workspace.tsx`. On 16 Oct local DEV temporarily ran `release/migration-review-export-20261016` lacking both; switching back to `codex/migration-intelligent-planning` restored Open Migration Workspace. When a feature disappears, **check current Git branch and file/route existence first**, not permissions or unrelated AWS resources.

## 7. ROLES, PRIVILEGES, WORKFLOW
Recorded roles: **Admin, PM, DevOps Lead, Cloud Engineer, Security Officer, Viewer**. Separate role-based navigation visibility, read access, create/update actions, approval authority, and environment/tenant scope. Multi-tenant authorization must be enforced server-side, not simply by hiding buttons. Recorded approval chain: **Business Owner → Security → CloudOps → Final Approver** where applicable. Role names and workflow actors are **not necessarily 1:1**; check configured role-to-approval mapping. In a DEV screenshot user `syr@deloitte.com` had Cloud Engineer role and the panel “No approval action is available for your role at this stage”; this is not evidence that the role cannot open Migration Planning. Do not bypass governance by changing a role to Admin merely to reveal a link.

Proposed RBAC verification matrix (DESIGN CHECKLIST, NOT VERIFIED RULES):
| Operation | Admin | PM | DevOps Lead | Cloud Engineer | Security Officer | Viewer |
|---|---|---|---|---|---|---|
| Read authorized tenant/customer/environment/cluster data | verify | verify | verify | verify | verify | verify |
| Manage customer records | verify | verify | verify | verify | verify | no mutation expected |
| Create/edit environments or cluster requests | verify | verify | verify | verify | verify | no mutation expected |
| Create/update migration planning drafts | verify | verify | verify | verify | verify | no mutation expected |
| Submit/approve each workflow stage | stage-specific | stage-specific | stage-specific | stage-specific | stage-specific | no approval expected |
| Manage users, roles, and tenant access | verify | verify | verify | verify | verify | no mutation expected |

Retrieve policy definitions and tests; replace every `verify` only with evidence. Approval authority must not be inferred from job title.

## 8. TECHNICAL STACK AND PRINCIPLES
- Frontend: Next.js (release build reported 16.3.4), React/TypeScript, modular components and CSS modules, Cognito OIDC; development `npm run dev -- --port 3000` in local frontend directory.
- Backend: Python 3.12 serverless AWS API Gateway → Lambda; Pydantic v2 validation; data/access services; SAM/CloudFormation. Other stack components exist but must be discovered per module rather than generalized.
- Persistence: PostgreSQL-compatible Aurora/RDS Data API in PROD; multi-tenant schema established previously (initial backend baseline reported 21 tables, but schema count is historical); SQL migrations checked into repository; avoid speculative schema updates.
- Infrastructure/deploy: SAM/CloudFormation for selected backend; ECR immutable Docker image and ECS/Fargate for frontend; Cognito for identity; CloudWatch for logs; AWS CLI profile `navigan` as documented. Network, ALB, DNS, secrets, IAM and DB service topology must be read before changing.
- Security: least privilege, tenant-safe database queries, authenticated API routes, secure secrets handling, no tokens in logs, auditable approvals, read-only-first verification, targeted tests, no forceful changes to active/remote resources.
- API-first rule: UI must call backend APIs; avoid hidden direct infrastructure calls from browser and hardcoded discovery results. Verify API contracts and enforce backend authorization.

## 9. DEV BUILD, RUN, TEST AND DEPLOY STANDARD
1. Use `/mnt/b/Langchain_Ai/Navigan-migration-test`, confirmed working on `codex/migration-intelligent-planning` as of last session. Run `git status --short`, `git branch --show-current`, `git log -1 --oneline`; do NOT discard uncommitted changes.
2. Build and run frontend LOCALLY: `cd frontend`, `npm ci` when lockfile/dependencies change; use `npm run dev -- --port 3000` for ordinary UI development; use `npx tsc --noEmit` and relevant tests before commit. Do not Docker-build for every frontend iteration.
3. Use existing DEV API Gateway/Lambda/RDS backend; actual endpoint/environment variables are to be checked, not guessed. When backend work changes, run targeted pytest and contract checks; deploy only the DEV Lambda/stack with a reviewed change set. Do not apply PROD migration scripts to DEV blindly or vice versa.
4. For DEV changes, follow: scope → minimal code edits → TS/backend tests → local browser/API acceptance → commit to proper working branch → reviewed PR/merge. Keep `.env.local` private/untracked and never copy build settings between DEV/PROD without verifying issuer, client, app URL, callback URLs, target API origin.
5. Avoid new git worktrees without a clear need; existing migration worktree is preferred. Build/test effort should be proportionate to changes.

## 10. PROD BUILD, DEPLOY, ROLLBACK STANDARD
**Current manual controlled release method, pending standard GitHub Actions pipeline.** Production already received migrations 025/026 and migration-only backend routes on 16 Oct; NEVER rerun as a standard deployment ritual.

1. Identify exact release commit and diff, including generated files, shared imports and excluded components. Stage in isolated release checkout; never assume a branch name guarantees identical code.
2. Run targeted backend tests, TypeScript, frontend tests, production `next build`/Docker build, security checks, and check API/DB migration compatibility. On last release 70 selected backend tests passed while 3 connector-related tests failed due excluded connector scope — record this as **unresolved test gap**, not “all tests passed.”
3. Build frontend image from exact controlled release source with verified **production** OIDC public environment: `NEXT_PUBLIC_OIDC_CLIENT_ID`, `NEXT_PUBLIC_OIDC_AUTHORITY`, `NEXT_PUBLIC_APP_URL`; inspect files for CRLF (`\r`), malformed shell values, and environment leakage. Next.js `NEXT_PUBLIC_*` values are build-time embedded. The 16 Oct login failure was traced to client ID containing a trailing `\r`; fixed locally by CRLF normalization and corrected image build. Never use naive `source .env.local` when its formatting is unknown, and do not print credentials. Verify OIDC issuer/client/callback by read-only inspection before build.
4. Push to ECR with unique immutable version tag, inspect ECR SHA256 digest, pin digest in new ECS task definition copied from the stable production task definition (only change the frontend container image). Do not rely on mutable `latest` tags.
5. Deploy only `navigan-frontend-Service-vMtHq9h7A9mz` in its dedicated ECS cluster, then `aws ecs wait services-stable`, and confirm EXACT task revision, 1/1 running, `COMPLETED`, and correct image digest. ECS health alone does NOT establish login success.
6. Smoke test fresh incognito login, Cognito callback, dashboard, customer/environment/cluster read-only navigation, Migration Workspace, approved migration and Source → Target → Compatibility → Remediation → Plan → Review & Export; verify saved draft and export with non-destructive data. Check CloudWatch/API errors and browser network request path/status without transmitting sensitive token/callback parameters.
7. For serverless API release use reviewed SAM/CloudFormation change set focused on **MigrationFunction and explicitly authorized migration routes**. Prior broadly generated SAM change set attempted to modify six nested stacks and was intentionally avoided. Compare change set before execution and block any connector/other-stack modifications.
8. Database changes are sequential, backward compatible, separately approved and validated. PROD migrations `025` and `026` committed on 16 Oct. Preflight schema status before running any further migration.
9. Rollback plan: prior ECS task definition/image if verified viable; retain image digest and previous task ARN; no automatic rollback of database or APIs without impact analysis. On 16 Oct task `:3` rollback did not restore login, demonstrating that UI rollback alone does not always solve authentication.
10. Freeze unrelated services while addressing a regression; diagnose error and origin before redeploying again. Document cause and close acceptance checklist.

## 11. ABSOLUTE INFRASTRUCTURE EXCLUSIONS
**Never inspect, change, restart, deploy or alter `nimbusops-frontend-cluster` (unrelated application).** Never modify existing source/cluster connector, `MigrationConnectorFunction` Lambda or its RBAC, private EKS cluster, GitOps, production/development tools-gateway services, or unrelated Aurora datasets without a separately approved, explicit scope. During the October production release only isolated Migration Management API Lambda/routes and Navigan frontend ECS were authorized, with database schema changes separately approved/applied. `kmf-p9-smk-s` unrelated target should not be touched. Avoid speculative IAM/Cognito changes. No executing actual migrations on customer workloads without an entirely new approved scope.

## 12. ACTIVE PRODUCT QUALITY/RELEASE CHECKLIST
- Customer Management: tenancy, lifecycle, roles, API consistency, audit, provider mapping.
- Environment Management: customer associations, creation/edit controls, state, approvals, region/provider mappings.
- Cluster Management: discovery fidelity, nodes, namespaces, workloads, topology, dependencies, role scope, approved provisioning inputs.
- Migration: source/target counts and freshness; namespace selection; graph edges and legends; scope summary includes Headlamp-selected objects/dependencies; compatibility evidence; remediation classification; draft save/resume; API-driven contracts; Review & Export; no execution actions.
- Security: Cognito/OIDC callback and public env, API authentication/authorization/tenant isolation, scoped secret access, secure logs, least privilege.
- Engineering: branch hygiene, automated unit/integration/type/API tests, scoped build artifacts, release traceability, rollback, observability, UI smoke/E2E.
- Documentation: user stories/specification, ADRs/decisions, API catalog, architecture diagram, environment inventory, RBAC matrix, schema migrations, acceptance criteria and known gaps.

## 13. STANDARD CI/CD GOAL (NOT YET IMPLEMENTED)
Design GitHub Actions with AWS OIDC short-lived credentials, PR lint/tests/type checks, API/DB migration review, Docker vulnerability scanning, isolated backend SAM change-set review, immutable ECR digest, protected DEV/PROD environments and human PROD approval, one controlled deploy button, post-deploy authentication/API/UI smoke tests, audit record and rollback. DEV frontend is currently local; define explicitly if/when an AWS-hosted DEV frontend is introduced. Do not present proposed automation as an existing pipeline.

## 14. DAILY START PROCEDURE
When given this prompt and today's objective:
1. Summarize task and relevant scope in 3–5 lines; say what remains UNKNOWN.
2. Identify authoritative working checkout, branch, current commit and `git status` **only if needed**. Verify AWS profile/account/region/current deployment only if task involves cloud resources.
3. State exact intended files/APIs/data/infra touched and explicit untouched resources.
4. Give a short implementation plan and definition of done before risky edits.
5. Prefer one cohesive command block or precise patch; avoid churning through approaches.
6. Validate with the minimum appropriate unit, contract, TypeScript and smoke tests.
7. Record changes, commit/PR, deployment, known issues, next steps in the Daily Session Checkpoint; never label untested functionality “complete.”

## 15. DAILY SESSION CHECKPOINT TEMPLATE
Date / timezone: ________ (Asia/Kolkata)
Objective for today: ________
Current branch / commit / working tree status: ________
DEV URL / backend endpoint actually checked: ________
PROD task revision / backend stack actually checked (if applicable): ________
Work completed since last checkpoint: ________
Build/test outcomes and failures: ________
Deployed changes (environment/resource/version): ________
Known blockers/risks: ________
Scope explicitly excluded: ________
Next action (one prioritized task): ________
Decision / approval needed: ________
Rollback / recovery pointer: ________

## 16. CURRENT SNAPSHOT AT BASELINE DATE (16 OCT 2026)
- PROD login **working per user confirmation** after auth-fixed image, ECS frontend task definition `:5` complete, one task running.
- PROD migration backend and schema 025/026 deployed; end-to-end Review & Export regression coverage still needs recorded acceptance evidence.
- DEV `localhost:3000` had no Open Migration Workspace while on branch `release/migration-review-export-20261016`; source comparison confirmed missing `/plan` route and planning workspace module. Switching back to `codex/migration-intelligent-planning` restored the workspace; user confirmed DEV working.
- Next recommended milestone: stabilize feature acceptance and create consistent gated DEV/PROD CI/CD process; avoid more ad hoc production releases.

## 17. REQUIRED FUTURE RESPONSES
Do not ask me to repeat established project architecture. If you lack a fact, mark it UNKNOWN and perform a read-only verification when needed. Never conflate intended feature scope with verified implementation; never conflate local DEV with PROD. Before changing approach, provide: current method, suggested change, reason, risk, impact, and need for approval. Never change branches, delete untracked files, force-push, run broad SAM/CloudFormation deploys, rebuild connector, or touch unrelated clusters without explicit authorization. Once a fix works, record the proven root cause and do not reopen the same investigation without new evidence.
