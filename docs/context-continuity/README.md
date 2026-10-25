## Latest checkpoint — 25 October 2026

Read [NAVIGAN_SESSION_HANDOFF_2026-10-25_LATEST.md](./docs/NAVIGAN_SESSION_HANDOFF_2026-10-25_LATEST.md) first. It supersedes conflicting status in older entries below.

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

## PROD frontend deployed — 23 October 2026 (Asia/Kolkata)

User terminal output confirms successful preparation and execution of /mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-prod-frontend-necjkwes/release-plan.json. Current deployed frontend: arn:aws:ecs:ap-south-1:905418045935:task-definition/navigan-frontend-TaskDefinition-j9W80aX9PBkf:9. Rollback task remains the same family :8. Built from branch commit b461886889d7c35d0b4aaf47fa9d5d0ef40420c9; immutable running image verified as 905418045935.dkr.ecr.ap-south-1.amazonaws.com/navigan/frontend@sha256:cfe98cb5d0627237424cd925a43939eb6d6d4a445750dd4c1c1370929e5f980e.

Release helper reported frontend deployment success, verified running image and passing public health/login HTTP checks. Backend/schema/workspace storage, scheduled repository collector and image polling service were already deployed and preflight verified. This supersedes historical frontend-pending/task-:8-live statements below. Do not rerun preparation or deployment merely to resume the session.

Remaining validation: fresh authenticated sign-in at https://navigan.click; Dashboard/Customer/Environment/Cluster navigation; Migration Overview and new assessment/discovery/scope/Collect & export workflow with PROD-specific source access. Real PROD collection/export and source-agent compatibility still need workflow evidence. DEV data was not copied into PROD. Deployment completion does not establish target readiness, workload migration or traffic cutover. Broader migration UI redesign remains on hold. Source agents and the unused extra recovery bucket were not changed.

---

# Navigan Context Continuity Kit

**Updated through 23 October 2026 (Asia/Kolkata).** Includes the completed DEV artifact workspace/collection/export work, source recovery evidence, accepted platform theme/header changes, discovery/scope separation, Files & images navigation, and the user-accepted Migration Overview.

This is the readable repository copy of `NAVIGAN_CONTEXT_CONTINUITY_KIT`. Paths below are relative to `docs/context-continuity/`. The root `AGENTS.md` points agents here. The recorded feature release is not necessarily the current branch HEAD after documentation commits.

Read in this order:

1. `docs/NAVIGAN_SESSION_HANDOFF_2026-10-23_LATEST.md` — authoritative current recovery point and detailed evidence.
2. `docs/NAVIGAN_DAILY_CHECKPOINT.md` — latest status, followed by historical checkpoints.
3. `docs/NAVIGAN_MASTER_CONTEXT.md` — latest override, followed by historical context.
4. `docs/NAVIGAN_DAILY_START_PROMPT.md` — paste into a fresh Codex/chat session with the latest handoff.

**Current branch:** `new_migration_approach_18oct26`.
**Latest verified feature release:** `ba88ea15ac73aea34657ed8316685d2012c1e28e`.
**Latest accepted visual baseline:** Migration Overview, user: “much better”.
**Latest collection follow-up:** Check sources → Collect & export, one workspace toolbar, named artifact/source/copy progress, active read-only updates; user acceptance pending.
**Broader migration workflow redesign:** explicitly on hold; resume only when the user chooses to.

The workspace export was downloaded successfully (14 collected artifacts, 2 historical exclusions). This is not target readiness or migration execution. Recent releases are frontend-only and do not require redeploying the backend, workers or source connector. Historical DEV deployment evidence and current API limitations are recorded in the latest handoff.

Preserve all older handoffs, archived prompts and scripts. Older files may say CURRENT or list old blockers, branches and next tasks; the 23 October handoff supersedes those claims. No credentials or signed download URLs are stored here.
