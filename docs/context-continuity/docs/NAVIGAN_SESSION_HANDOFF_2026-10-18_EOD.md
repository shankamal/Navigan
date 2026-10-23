# Navigan — Source-first implementation and blocked discovery handoff

**Work recorded:** 18 October 2026, through 23:54 IST.  
**Continuity kit updated:** 19 October 2026 (Asia/Kolkata), when this chat resumed.  
**Evidence boundary:** Runtime observations below are the user's 18 October outputs. No new AWS, database or customer-cluster verification was performed on 19 October while updating this kit.

Read this file first. It supersedes the active-branch, next-task and implementation-status statements in the 17 October handoffs. Those documents and the 67-capability gap tracker remain historical architecture references; the tracker has not been re-scored.

## 1. Resume here — confirmed blocker, still unresolved

The running source connector serves a different registration from the DB Schenker assessment. The namespace catalogue exists, but detailed inventory and assessment have not completed. Do not describe the real DB Schenker migration as successfully assessed.

| Item | Last observed value |
|---|---|
| Assessment | `DBS_Migration_Assessment` |
| Migration ID | `MIG-9beaa527a0754613aa1d8e7a7ee6a8af` |
| Customer | `Db Schenker` |
| Customer ID | `CUS-80d155e7f63f43a099059864c628a6e0` |
| Assessment source registration | `SRC-2f0e434335e04ef0bdccd74cb3322f2c` |
| Running pod source registration | `SRC-ae85e62d759d47fabf8eb87610ea39b9` |
| Running connector | `SCC-862f8aa721e341d0bf4d59a8e722ca90` |
| Connector assignment | `NONE`, status `IDLE`, migration ID/version null |
| Assessment backend state | `DISCOVERY_PENDING`, version `5` |
| Namespace catalogue | Present: catalogue version `1`, migration version `2` |
| Detailed inventory | `null` |
| Assessment report | `null` |

**Confirmed cause of this wait:** The live connector is not claiming work for the source registration referenced by this assessment. Matching cluster display names are not proof of registration identity. The owner/customer of the running `SRC-ae85…` registration is still UNKNOWN. Do not assume it belongs to Acme, BlueSky or DB Schenker without reading its record.

**First task:** In the signed-in DEV UI's Network responses, inspect the source registration list for DB Schenker (`GET /api/v1/source-clusters?customerId=CUS-80d155e7f63f43a099059864c628a6e0`) and, where authorised, the record for the running source ID. Compare IDs, customer ownership, connector ID/status and heartbeat. Supply only relevant non-secret fields. Inspect the pending migration/registration references before selecting a supported repair.

Do not restart/reinstall the healthy connector, create another registration, delete or merge records, reassign a registration across customers, or update database ownership as a speculative fix. Reinstalling the same physical cluster under another registration can overwrite the fixed connector deployment identity. Once ownership is known, prepare the smallest supported association repair with customer isolation and version checks; the pending migration is not currently editable as a normal DRAFT, so do not simply tell the user to change a dropdown or PATCH it.

## 2. Repository, environment and release position

- Repository: `https://github.com/shankamal/Navigan`.
- **Active branch:** `new_migration_approach_18oct26`. The former `codex/migration-source-ui-compact-topology` and `codex/migration-intelligent-planning` references are historical, not instructions to switch branches.
- User WSL checkout: `/mnt/b/Langchain_Ai/Navigan-migration-test`.
- DEV frontend: local Next.js, `http://localhost:3000`; DEV backend remains AWS API Gateway/Lambda/RDS. No new architecture/worktree was requested for the user's machine.
- Latest pushed and user-pulled commit: **`428cd3bc2298734e96e5cab5be44ce9dd9781aca`** (`428cd3b`). One remote commit contains the 19-file source-first discovery/assessment increment.
- User confirmed a fast-forward pull from `807f93f` to `428cd3b` and successful DEV deployment with `python3 scripts/deploy-source-connection-screen-dev.py --profile navigan --apply`.
- Deployment output confirmed both `MigrationConnectorFunction` and `MigrationFunction` updated and `MIGRATION_SOURCE_FIRST_ENABLED=true` enabled for the DEV API function. Backup directory reported: `/tmp/navigan-source-connection-dev-tb5pa60s` on the user's WSL host. Preserve it if still available; its continued existence is not verified today.
- The deployment script patches the existing two DEV Lambda ZIP packages, includes `assessment_engine.py`, preserves dependencies, uses revision checks, and targets account `905418045935`, region `ap-south-1`, stack `navigan-ashok-dev`. No API Gateway, IAM, database or unrelated resources were changed by that deployment according to its output.
- **No production deployment was performed during this work.** Last historical user-confirmed PROD frontend remains task revision `:8` from `84ea9ee` as recorded in the 17 October handoff; not reverified on 18/19 October.
- The agent's temporary local snapshot commits differ from remote commits. Do not direct the user to pull scratch-only commits or treat the agent's scratch checkout as the user's live WSL checkout.

## 3. User decisions and intended flow

- **DB Schenker and JPMC are real approved customers/environments. Other customers are dummy dashboard/demo data.** Use dummy data for UI tests and clearly label preview fixtures. Do not reassign demo infrastructure into a real customer's ownership without establishing the intended association.
- DB Schenker is the selected customer context for the migration work. A new assessment defaults to its accessible ACTIVE record when the normalised customer name matches; no customer ID was hardcoded. Customer remains changeable before creating an assessment; existing saved drafts retain their customer association.
- Intended sequence: **New Migration Assessment → Source connection → Source discovery and source assessment → Open Migration Workspace → Choose migration scope → Target selection and compatibility for selected scope → Review and approval → Execute**.
- Implementation proceeds step by step. The new discovery step is implemented; this does not mean all subsequent workspace stages, target adapters, AI transformation or execution have been rebuilt/completed.
- Application/workload-centric migration and shared Helm/YAML/script artifact extraction remain the broader architecture direction from the ideation document. Namespace selection must not automatically imply migrating every workload.
- Approved visual direction: **Option 4 unified canvas**, consistent Navigan typography and restrained Deloitte green. Mandatory fields show `*`; field guidance/tooltips and action validation are required.
- Intended connector model: one connector per physical cluster, reused across assessments, with explicit customer-to-cluster authorisation for shared clusters. **Cross-customer shared-cluster authorisation is NOT implemented.** Current registrations/lists remain customer-scoped. Never bypass tenant filtering to make the dropdown display another customer's connector.

## 4. Source connection work implemented and pushed

Remote milestones during 18 October:

| Remote commit | Increment |
|---|---|
| `4f87ea3` | Option 4 source connection UI, tooltips, mandatory markers, action validation |
| `9e73069` | Restored draft name/source-selection editing and Save changes |
| `807f93f` | Stable installation progress, background polling separated from form busy state, single Connect/Verify primary action, active-customer connector notice |
| `428cd3b` | Source-first discovery/assessment screen, source-only backend support, workspace gate and DEV deployment-script alignment |

Source connection collects assessment name, active customer, register/reuse choice, source cluster name, platform/distribution/location/provider/region, delivery method, AWS account/SSM instance, remote kubeconfig path and optional role ARN. The currently implemented migration path is self-managed Kubernetes; unsupported paths remain unavailable rather than pretending to work.

- Loads accessible ACTIVE customer pages; source list is filtered by selected customer and excludes revoked registrations.
- Reuse uses the existing registration without installing another connector. Duplicate SSM host/region/account/kubeconfig matching is a client-side reuse hint/guard, not a global physical-cluster uniqueness constraint.
- Save draft persists without installing. Register/connect requests installation/enrollment through existing APIs.
- Restored DRAFT assessment name and source selection can be edited; Save changes updates the same migration. Customer remains fixed. Connected cluster attributes shown as reference remain read-only; switching to Register new cluster opens input fields.
- Installation shows a steady spinner and progress status rather than disabling/re-enabling the whole form on each heartbeat poll. Primary action changes from Connect source to Installation in progress to Verify connection; no simultaneous duplicate Connect and Verify primary buttons.
- A recently active connector for the selected customer produces “Connector is already established for this customer” with a reuse action. This is not a statement that other customers may use it.
- A recent heartbeat verifies connectivity; inventory/Kubernetes access is not inferred from enrollment. Continue to discovery validates saved state and verification freshness, then opens the discovery route.

## 5. Source Discovery & Assessment increment

DEV routes: `/migrations/{migrationId}/discovery` and `/migrations/{migrationId}/plan`. Entry routing for DEV opens connection for a source-first DRAFT, otherwise the new discovery screen. The redesigned routes are gated to development with `MIGRATION_SOURCE_FIRST_ENABLED` not false on the frontend; production keeps legacy rendering paths.

New screen includes migration/customer/source context, steady progress phases, namespace/workload/resource/finding counts, searchable namespace catalogue, namespace-filtered paginated resource inventory, source Kubernetes/node/architecture/observation facts, and source findings/remediation. No fixture inventory is hardcoded into the application; preview fixtures were explicitly sample data.

Actions are explicit: **Discover source inventory** requests the namespace catalogue; once `INVENTORY_READY`, **Run source assessment** requests detailed inventory and source assessment. Status refresh does not auto-start either operation. Polling preserves rendered evidence, is bounded by a two-minute automatic-check window, and provides Refresh status and an explanatory timeout message. The timeout is not itself evidence of connector failure or successful assessment.

**Open Migration Workspace** is gated on completed backend status plus matching assessment/inventory digest and migration-version evidence. New reports also bind the source registration ID; changing source registration does not permit an old report to satisfy the gate. Planning-only version increments may retain access with the same source evidence. A DEV workspace entry wrapper also checks completion instead of relying only on button visibility.

Backend changes:
- `assessment_engine.assess(..., source_only=True)` retains source rules but defers target runtime checks; marks summary mode `SOURCE_ONLY` and target status `NOT_ASSESSED`.
- Connector ingestion uses source-only mode for a MANUAL source-first assessment without a selected target. Existing target-based assessment behavior is preserved when a target is already selected.
- Stored summary includes the source registration ID; frontend schema retains mode and source ID.
- Discovery API client allows omission of a one-off connector token when using a registered source connector.
- Source-first review submission without target selection is rejected server-side. This is not a claim that every future scope/compatibility/approval gate is completed.
- Target compatibility percentage is not displayed as a result of this source-only step. Target environment and compatibility remain subsequent workspace actions.

Key files: `source-connection-screen.tsx`, `source-connection-validation.ts`, `source-connection-entry.tsx`, `source-discovery-screen.tsx/.module.css`, `source-discovery-state.ts`, `source-workspace-entry.tsx`, migration model/service modules, discovery/plan route pages, and backend `assessment_engine.py`, `connector_handler.py`, `service.py` under `src/navigan/modules/migration_management/`.

Validation at `428cd3b`: **30 frontend tests, 65 selected backend tests, TypeScript and preview build passed**. Browser preview verified namespace filtering, resource inspection and no horizontal overflow at the available laptop viewport. These are scoped tests/sample-data checks, **not real DB Schenker end-to-end acceptance**.

## 6. Runtime diagnostic evidence at pause

SSM source host: `i-08e28d9b2242cbd53`, AWS CLI profile `navigan`, region `ap-south-1`. On the source host use `sudo kubectl --kubeconfig /etc/kubernetes/admin.conf`; the laptop's default kubeconfig previously pointed at another EKS endpoint and timed out.

Namespace `navigan-migration`; deployment `navigan-source-connector`; observed pod `navigan-source-connector-698fc59b48-sm52d`: **1/1 Running, zero restarts**, age about 40 minutes in the user's output. There was one deployment/pod, not three separate connector pods. The last-15-minute log command returned no lines. The agent logs failures but is silent during successful/idle cycles; empty logs do not prove discovery completion.

Printing `NAVIGAN_SOURCE_CLUSTER_ID` was blank, while `NAVIGAN_SOURCE_CONNECTOR_ID` was `SCC-862f8aa721e341d0bf4d59a8e722ca90`. The source ID variable is not required by this agent: backend lookup resolves the registration from the connector ID. The later authenticated assignment response confirmed the different source registration and IDLE state; the blank variable was not the cause.

The paused DB Schenker record is **an older target-based assessment**, created 18 October 12:01 UTC, not a newly created MANUAL source-first draft. Its sourceConfiguration lacks discoveryMode. It already contains target `dbs-sims-clus2`, cluster ID `CLU-ab5d1625584e4c7197112c7c590698ae`, environment `ENV-32367b457b2948cab4513bc20b393772`, approved version `8`, PRIVATE endpoint access. Scope includes calico-system, default, headlamp, ingress-nginx, migration-demo, navigan-migration, retailflow and tigera-operator; kube-system/kube-public/kube-node-lease are excluded, persistent-data and cluster-scoped migration flags false. These saved values are historical configuration, not validation of current approval or target readiness.

Catalogue observed 18 October 15:21:20 UTC: Kubernetes `v1.37.1`, 3 nodes, amd64, 8 namespaces. Catalogue digest: `ec1430646ec8b055fa6bffe83421732be43f6256ce33a71c3bdde47352c183bd`. Detailed inventory and report were null at migration version 5 after the latest assessment request. A source connector claiming this request would move it from DISCOVERY_PENDING to DISCOVERING; that had not happened for this migration.

The diagnostic `migration_connector.agent.fetch_assignment()` is authenticated and may claim/advance an available assignment; it is not a purely observational endpoint. Do not run repeated collection/submission cycles or print environment credentials for debugging. Never request/display connector tokens, secrets, kubeconfig contents or HTTP authorisation headers.

## 7. What remains unimplemented or unverified

- Correct ownership of the running source registration, duplicate registration history, and the supported association repair are not established.
- No registration/customer remap, migration rebind, connector reinstall, deletion or merge was performed at pause.
- Real DB Schenker detailed discovery/assessment remains blocked; the new source-only mode has passed tests but not this real runtime path. The paused assessment would take the existing target-based path because its target is already selected.
- Cross-customer connector sharing, server-side physical-cluster deduplication and safe registration reconciliation require explicit design/implementation. Do not treat the design discussion as deployed capability.
- The subsequent workspace was linked and gated, not fully redesigned to implement the entire new ideation. Preserve the earlier gap tracker limitations for Helm/YAML/script provenance and splitting, dependency closure, PVC/DB migration, controlled AI/RAG, packaging, execution, validation, cutover and rollback.
- No executed workload migration, target environment mutation, production change or broad infrastructure deployment has been demonstrated.

## 8. Short recovery prompt

Continue Navigan on `new_migration_approach_18oct26`, last user-confirmed DEV deployment `428cd3b`. Read this handoff before the older context. Source connection Option 4 and source-first discovery UI/backend are implemented and deployed to DEV; 30 frontend/65 backend tests and TS passed, but DB Schenker runtime discovery is blocked. Migration `MIG-9beaa527a0754613aa1d8e7a7ee6a8af` waits at DISCOVERY_PENDING v5 for source `SRC-2f0e434335e04ef0bdccd74cb3322f2c`; the healthy live connector `SCC-862f8aa721e341d0bf4d59a8e722ca90` serves `SRC-ae85e62d759d47fabf8eb87610ea39b9` and returns IDLE/NONE. First verify source-registration ownership and references through authorised API reads. Do not reinstall, reassign, delete, switch branches, weaken customer isolation or create more registrations speculatively. DB Schenker/JPMC are real; others are demo. Resume with this association diagnosis, not another UI redesign or a claim that discovery completed.
