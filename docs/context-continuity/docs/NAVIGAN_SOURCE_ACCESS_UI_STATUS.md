## 2026-10-25 — Login viewport sizing correction

- Follow-up to the production screenshot: oversized width-driven typography and spacing made the normal login overflow on shorter / scaled laptop viewports.
- CSS-only fix: height-aware typography and branding, 400px maximum form width, compact fields and gaps, fixed viewport allocation for the desktop illustration and provider row. No hidden-scrollbar workaround.
- Retains the approved coloured king, graphite panels, logos and deep-green button. No authentication, API or backend changes.
- Browser fixture using actual login components and application CSS: normal login document scrollHeight equals clientHeight at 1536x696, 1280x580 and 390x650; no horizontal overflow. Fixture preview build and 14 login/auth-entry tests passed. Live Cognito smoke testing remains required after deployment.
- Prepare a fresh frontend release from this branch and execute its newly printed release-plan.json. Earlier prepared images do not contain this sizing fix.

## Approved login splash and Navigan logo — 2026-10-25

The user approved the attached image(20261025-115255).png for implementation. It selects the coloured royal navigator/harbour illustration, three-facet directional Navigan logo, white story pane, charcoal sign-in pane, Welcome to Navigan heading and deep-green button. This explicitly supersedes the briefly proposed grayscale king and lime sign-in button. Preserve the accepted platform theme and migration workflows.

Implemented SignInScreen and one scoped responsive login stylesheet, replacing obsolete competing login rules and nested-card scrolling. Existing PublicShell uses the reverse Deloitte mark; the new Navigan mark also replaces the stacked sidebar logo, using white/green on dark compact surfaces. Standalone generated/optimized WebP assets are committed with code. Existing Cognito calls, session handling, SRP/challenges, reset submission and backend APIs remain unchanged. Password visibility is a presentation control; it does not submit and resets when the form resets or completes a request. The approved desktop composition adapts to laptop height; phones prioritize the full-width form and omit the decorative story panel.

Validation: 23 focused login/auth-entry/shell tests and production build passed. Cloud browser verified the real components/styles in an isolated local presentation fixture at desktop, laptop and phone sizes, and the recovery/back interaction. Production credentials were not entered. The final comparison, screenshot and QA report are in docs/design/login-splash-20261025; no application rendering error was observed in the checked fixture, while unrelated browser-extension metadata errors were present. Some generated illustration linework/provider logo differences are recorded as P3 fidelity limits.

Next: pull and use deploy-frontend-prod.py --prepare, then execute the newly printed release plan. Do not reuse the earlier revision-16 preparation plan for this splash. No backend, migration API, database, collector or source-runtime release is needed. Verify actual production sign-in, MFA and recovery after rollout. Frontend revision 16 was prepared in the conversation; execution output for it was not provided before this design task, so read actual deployed revision in preflight rather than assuming it.

## Page loading and Migration Overview bundles — 2026-10-25

Production summary restoration from 62d4b6cfde1e758e9cc91866892338fc9bbc38a3 was executed by the user. The helper verified all three summary routes and Lambda ZIPs. The subsequent authenticated dashboard Network screenshot shows summary HTTP 200 at about 420–434 ms, list requests about 397–437 ms and no pageSize=1 fallback count burst in the capture. This is one successful observation, not an all-screen latency SLA or proof that every cold start is resolved. The browser reported load around 5.98 seconds; Fetch/XHR alone does not identify the remaining critical path. Broader UI inconsistency stabilization is deferred.

The user asked to improve remaining page loading, including Migration Overview. This frontend-only optimization splits sign-in presentation from the shared AuthGate using a deferred component without changing session checks, redirects, Cognito configuration or form logic. Migration Overview no longer imports/re-exports the legacy creation wizard and report; the creation route and tests import dedicated entries while preserving source-first routing. Dashboard, shared shell and overview links now wait for hover, keyboard focus or touch before enabling Next.js prefetch; normal links and modified clicks remain unchanged. Unrelated routes no longer prefetch merely because their links enter the viewport. The accepted Graphite layout, fonts, chart values and workflow actions are preserved.

Validation: 41 focused frontend tests passed, including sign-in/redirects, login form, shell permissions, overview/create/report behavior, summary fallback and link intention. Production compilation, TypeScript and build completed. Inspection of generated Migration Overview client references found no eager sign-in screen or wizard module and no sign-in form/wizard action text in its initial referenced JavaScript. No before/after production bundle-size or six-second load improvement is claimed. No backend, API, database, Lambda, source-agent or collector changes are included.

Next: prepare and execute a new frontend production release using the existing deploy-frontend-prod.py helper. Keep production revision 15 until the new plan is executed. Test signed-in Dashboard and Migration Overview, creation and sign-out/sign-in, hover/focus navigation, and capture Network All plus performance timings on cold/warm loads. Remaining bottlenecks need measured asset/request timings rather than speculative database or Lambda tuning.

## Production performance: summary API restoration — 2026-10-25

The user deployed frontend revision 15 from af909faa6ef4e2c81b722d2485530bc8bbeec8b5; running image and health/login checks passed, and the user accepted the UI. Remaining UI inconsistencies are deferred to final stabilization. The current task is slow data loading across screens.

Three supplied browser Network screenshots show summary HTTP 404s followed by pageSize=1 fallback count requests. Successful list requests take about 4–8 seconds, while effective-access calls in the capture are about 200–480 ms. Branch code already implements scoped summary endpoints and client fallback. Production route/handler readiness requires live inspection; do not assert the precise missing layer or blame authentication/cold starts without evidence.

Added scripts/deploy-summary-apis-prod.py and docs/migration/summary-api-production-fix-20261025.md. The helper uses the existing prepare/execute production pattern, reads live protected list-route configuration, preserves deployed modules and native dependencies, adds only known summary handler/repository logic and missing summary routes, and creates a scoped change set for CustomerManagement, EnvironmentManagement and ClusterManagement. It preserves authentication settings, tenant scope and non-summary business logic; no schema, frontend, migration Lambda, connector or collector changes. Unknown deployed contracts stop for review. Original ZIPs/configuration/templates are saved privately. A working summary path replaces 28 legacy count requests with three aggregate requests; regular list calls and their latency remain to be measured separately.

Validation: 12 focused Python release/query/package tests and 4 existing frontend summary tests passed; CLI help checked. AWS credentials are unavailable to the agent. Next: user pulls the branch and runs the helper with --prepare, then executes the newly printed plan after scope validation. Confirm authenticated summary HTTP 200 and disappearance of fallback counts; measure remaining list durations before further tuning. No live production performance improvement is claimed yet.

## Dashboard layout, frozen heading and on-demand help — 2026-10-25

The user confirmed the migration UI on production frontend revision 14 was visually much better. Preserve that accepted migration navigation and Graphite theme.

This frontend-only update puts Cloud footprint, Active record coverage and Cluster workflow state first on the Dashboard. Compact Estate coverage and Operations summaries follow. The Platform command center title bar stays below the measured global top bar while scrolling; its title, freshness status and actions remain together. Chart columns and summaries adapt to available workspace width.

A shared circled-info help component replaces persistent explanatory paragraphs on the Dashboard and the core source access, discovery, scope, source checks and artifact workspace views. Help appears on hover, keyboard focus or touch, stays available while hovered, and closes with Escape or an outside click. Operational errors, progress, missing evidence and target readiness messages remain visible. This is not a blanket replacement of every legacy form's guidance.

Validation: 114 focused frontend tests passed. The production build, including TypeScript validation, completed successfully. Browser visual checks across resolutions and fresh authenticated workflow checks remain required after deployment. No backend, authentication, API, database, collector or source runtime changes are included. Existing inventory snapshots and saved S3 artifacts are preserved.

Deploy using the existing frontend production prepare/execute helper. This update is not yet deployed. Production revision 14 remains the observed baseline until a new release is executed and verified.

# Current checkpoint: migration UI workflow consolidation — 25 October 2026

The user resumed UI improvement and supplied nine screenshots spanning source access, Source & Discover, migration scope and artifact collection. Screenshots show fourteen of sixteen artifacts saved, including all seven container images, five repository files and two Headlamp recovery artifacts. Two historical Job entries need source review; collection does not establish target readiness. Production frontend revision 13 was previously deployed successfully from the workspace reconciliation release. No later frontend rollout is confirmed here.

This frontend-only change introduces a shared bottom action bar across source access, discovery, scope, target assessment and review; removes duplicated repository/registry setup from migration scope; and sequences Save & continue through source checks and artifact collection before target selection. The associated-resource card wall becomes a searchable, kind-filtered, paginated table. Selected workload names are expandable. Discovery adds a compact colour resource-composition donut, readable observation time and less nested scrolling. Repository files, Container images and Source recovery are separate collection categories with their own counts/actions. Workspace maintenance actions are grouped under Workspace options. Recovery no longer appears as image copying; missing S3 paths are not invented. Full image references remain accessible in row details. Provider marks are coloured, primary buttons remain deep green and new styles use the existing typography system.

Recheck sources remains available as a secondary evidence refresh after inventory/repository/registry access changes. It does not restart cluster discovery. Canonical source access setup stays reachable from Source & Discover and from artifact access failures. Existing backend APIs, payloads, authorization, readiness gates, collection jobs, historical review and target compatibility behaviour are preserved. No backend, infrastructure, authentication, connector or schema changes are part of this release. Shared physical connector/customer bindings remain a separate pending capability.

Validation: 122 focused frontend tests, TypeScript and local production build passed. Tests cover scalable associated-resource browsing, source readiness/ownership, stable action-bar rendering while source details load, preserved selection, sequential navigation, independent image jobs during source recovery, category-specific actions, export/error feedback and old snapshot retention. Browser visual checking was blocked because the available browser cannot reach the local preview server. Do not claim visual acceptance or authenticated production verification from unit tests. Details and screenshot-based findings are in docs/migration/migration-ui-workflow-review-20261025.md.

Next: pull the branch and review the frontend in DEV, then use the established deploy-frontend-prod.py --prepare and --execute of the newly printed release plan when releasing. No migration API/worker/source-agent redeployment is required for this UI-only change. Verify main and child screens, narrow-width action wrapping, dropdown placement, long resource names and keyboard/motion behaviour. Keep pending historical Job reviews and all saved workspace artifacts; do not repeat discovery, reinstall connectors, rotate working credentials or delete workspaces merely to apply these UI changes.

---

# Current checkpoint: workspace source-check reconciliation and verified artifact reuse

User confirmed the earlier inventory snapshot still shows the previously saved artifacts; a newer current-inventory workspace showed zero saved, no repository candidates and unchecked images. Screenshots of Check sources separately showed current repository candidates and available registry images. Workspace indices capture analysis at creation and do not change when source analysis completes; refreshing the workspace list only reloads collection state. Earlier advice to create a fresh index without preserving completed collection was insufficient.

The correction adds Update workspace index to the existing collection toolbar. It uses the existing create-workspace API to make a revised snapshot from current completed source checks, selects it and retains earlier snapshots. Repeating an identical analysis/scope returns the existing revised index. Creation now rejects incomplete/stale source analysis with SOURCE_CHECK_REQUIRED instead of creating an unchecked dead end. Create workspace remains disabled when a current index exists; updating it is an explicit action. Updates are disabled in the UI while collection/recovery is running or without edit access.

Within the same customer, assessment, source registration and configured bucket, exact repository commit/file/source identities and image reference/digest identities can reuse collected content. Reuse verifies prior index/record agreement, collection validation, immutable S3 object versions, SHA-256 evidence, size and KMS encryption. Images require complete digest-verified OCI archive evidence. Verified objects are copied server-side into the revised workspace prefix, checked again and recorded with current workload links, a reuse receipt and targetReady=false. Old database records and S3 objects are never modified or deleted. Changed/unavailable content, failed integrity/access checks, live exports, Helm recoveries and historical exclusions are not carried forward. These stay eligible for collection or fresh recovery as appropriate. Synchronous reuse is bounded to twelve objects, objects of at most five billion bytes, and six concurrent S3 copies with short transport timeouts; anything not reused remains ready for normal collection. No schema, route, infrastructure, IAM or worker runtime update is required.

Validation: 120 focused backend tests and 41 workspace UI tests passed; frontend TypeScript passed. Coverage includes current-analysis reconciliation, duplicate update handling, new prefix/version/checksum checks, wrong customer/source/assessment/bucket, changed commits/image identity, incomplete OCI archives, failed copies and preservation of old records, plus the previously disabled collection controls. These are local tests; authenticated production reuse and collection are not verified yet.

Deployment: use the existing scoped migration API prepare/execute helper first, then the existing frontend prepare/execute helper with each newly printed release plan. Do not reuse previously executed plans. After both releases, open Files & Images / Collect & export and select Update workspace index once; inspect the reused count and collect remaining available files/images. Do not reinstall the connected source connector, rotate working credentials, delete snapshots or restart discovery merely to apply this correction. Target validation remains separate, and broader UI redesign/shared physical connector customer bindings remain pending.

---

# Current checkpoint: eleven artifacts saved; PROD agent runtime evidence gap

The user configured the production image worker registry role and trust; UI progress subsequently reached 11 of 15 required artifacts saved, consistent with five repository files plus six ECR image archives. Remaining items are the tagged Headlamp image without a captured running digest and three live definitions (Headlamp Deployment and two historical periodic Jobs). These are not active background copies. Source-host read-only diagnostics confirmed the Headlamp Pod is running with a SHA-256 image identity, while the deployed production agent's collect_inventory lacks collect_runtime. The source runtime evidence capability used in DEV was not present in the production agent image.

This correction adds upgrade-source-runtime-prod.py for a single explicitly selected existing source/instance. It follows the prior DEV runtime ConfigMap overlay method, validates account/branch, checks the production connector API contract first, verifies source registration and API identity inside the existing pod, verifies read access, creates an immutable code ConfigMap, saves a private original Deployment backup and rolls only the named source Deployment. Image, credentials, security context, other agents and application workloads are preserved. A failed rollout restores the original Deployment spec with a revision check. No re-enrollment or manual database digest updates are used. This is an existing-agent upgrade; a runtime-capable immutable image still needs promotion for future physical source installations.

The production connector API release helper now also promotes models.py and deployment_sources.py, so the ingestion schema accepts and validates sanitized runtime evidence. It can add the validator module to older connector bundles while preserving native dependencies and unrelated files. The existing handler and assessment engine continue source-only discovery.

Validation: 79 focused runtime, connector, schema/deployment guard and assessment tests passed; CLI help checked. Neither this contract update nor the source runtime upgrade has been executed against AWS here. Next: pull and prepare/execute the scoped connector API release, then run the targeted source runtime upgrade with --apply. Run a fresh source assessment to capture owner-linked Pod image digests. A new inventory digest makes the prior workspace historical/stale: retain its existing S3 objects and use a fresh workspace index for fresh evidence; do not claim existing workspace pinning or automatic artifact reuse. Newly collected artifacts still need verification and eventual export. Source/target deployment and persistent data migration remain separate.

---

# Current checkpoint: PROD assessment passed; planning namespace guard correction

The user successfully deployed the scoped connector API promotion. The existing source connector retried its pending report, and the production UI now shows 8 namespaces, 30 workload controllers, 171 collected resources and 125 finding observations across 12 issue groups. GitHub and registry setup are verified. This confirms production discovery and source-only assessment, not artifact collection or target readiness.

Next workflow test reached Migration scope / Files & Images and hit NAMESPACE_OUTSIDE_ASSESSMENT while saving selected planning namespaces. The service still compared the selection to the initial migration_scope namespace preset, despite source-first discovery assessing all captured namespaces before planning selection. For a feature-enabled SOURCE_FIRST draft backed by a SOURCE_ONLY assessment, the guard now derives allowed namespaces from the digest-bound assessed inventory: namespaced resource identities plus explicit core/v1 Namespace records for empty namespaces. Legacy, target-bound or disabled workflows retain their preset-scope boundary. Snapshot/version/digest/resource checks remain unchanged; no assessment scope or inventory is rewritten.

Validation: 47 focused planning, namespace model, source-first and artifact tests passed, including rejection of unknown namespaces, stale digests and expansion in legacy/disabled workflows. This correction needs the existing scoped production migration API prepare/execute release. No frontend rebuild, connector API redeployment, source reinstall or rediscovery is required. After deployment, retry saving the selected namespace/workload scope in Files & Images, then continue artifact collection. Existing production image worker role authorization/trust remains to be verified before private ECR copying.

---

# Current blocker: production connector API promotion

GitHub and registry setup now show Verified. The source agent is healthy and gets the active SOURCE_INVENTORY assignment, but repeated cycles fail at submission. A read-only inventory collection succeeded and produced a small sanitized report. A subsequent normal submission returned HTTP 409 TARGET_CLUSTER_REQUIRED. The production assessment is MANUAL / ASSESSMENT_ONLY without a target, as intended before migration scope and target selection. Read-only inspection confirmed the separate production MigrationConnectorFunction has no source-first flag and lacks source-only handling. Earlier scoped API promotions updated MigrationFunction only; the connector ingestion Lambda was not promoted.

The existing branch connector handler and assessment engine already support source-only assessment. A new deploy-migration-connector-prod.py helper promotes exactly those two modules from the current branch into the existing connector ZIP, preserving native dependencies and other modules. It updates only MigrationConnectorFunction code and its source-first flag through a scoped nested CloudFormation change set, validates unchanged dependency reevaluations, saves private rollback files, and rejects unrelated resource changes, replacement, stale revisions, unexpected environments or package references. No migration API, frontend, IAM, schema, source installation, registration or credential changes are included.

Validation: 46 focused connector, source-only assessment and deployment guard tests passed; CLI help verified. The new helper has not been run against AWS here. Next: pull branch, run the connector helper --prepare, inspect its scoped plan, then --execute that newly prepared plan. The existing source pod should retry the pending inventory submission without another discovery run or reinstall. Refresh discovery status after deployment; live assessment completion is still unverified. Target compatibility remains a later workflow step, and image collector role authorization/trust still needs verification before collection.

---

# Source access navigation button styling

The user confirmed GitHub and registry setup now show Verified and discovery setup is ready. The Continue to discovery link worked but appeared as plain text because it used a CSS class whose rules target button elements only; Back to discovery status was also an unstyled link.

The frontend-only correction uses the shared button classes for both links: secondary Back to discovery status in the shared page header and primary green Continue to discovery in the readiness panel. Routes, access checks and readiness requirements are unchanged. Six existing source access setup tests and TypeScript passed. A new frontend prepare/execute release is required to show the styling in production. Until then, both existing plain-text links remain usable; source assessment testing can continue without waiting for this cosmetic release.

---

# Public GHCR setup verification correction

ECR setup verification passed after the user added the production API principal with its source-specific External ID to the existing registry role trust, preserving DEV trust. Public GHCR verification remained blocked. Read-only network diagnostics reproduced root registry HTTP 401 with a Bearer challenge, unscoped token HTTP 403, and a repository-scoped anonymous pull token HTTP 200 for the public Headlamp repository. No credential values were printed or saved.

The backend correction recognizes only the exact public GHCR root endpoint's expected same-host HTTPS token challenge as endpoint reachability and avoids the unscoped token request. Setup explicitly states that image-specific access is checked during analysis. It does not mark image content or target readiness verified. Private token/bearer verification, other registries, repository-scoped manifest token exchange, HTTP success requirements and trust protections are preserved.

Validation: 72 focused source-authentication and deployment-source tests passed. This backend correction must be deployed through the existing scoped production migration API prepare/execute helper. After deployment, retain Public / anonymous for GHCR, keep inventory-only unchecked, then Save and verify access and continue source assessment. Production image worker role authorization/trust still needs checking before collection. No frontend rebuild or connector reinstall is required for this correction.

---

# Latest correction: persistent source access navigation

The user confirmed the preceding frontend release deployed successfully, but the source access link was still unavailable in their workflow. Code inspection found that the only discovery link was nested inside a conditionally hidden progress panel and also depended on discovery action availability and access readiness.

The correction moves Configure source access into the shared Source & Discover page header beside Back to assessments whenever an assessment has a source registration. It remains available after discovery completion and when readiness is already satisfied; the incomplete-setup message refers to that header action. The existing setup page retains source/customer checks and backend readiness requirements. No backend, authentication, connector or infrastructure changes are included.

Validation: 26 focused discovery/setup tests and frontend TypeScript passed. Regression coverage checks the action remains visible while the completed progress panel is hidden and when source access is already ready. Production authenticated visibility still needs verification after this correction is deployed. Prepare a new frontend release plan from the latest branch, then execute that newly prepared plan. Do not reuse the previous executed plan or reinstall the connected connector.

Shared physical connector customer associations remain pending. Broader UI redesign remains on hold.




