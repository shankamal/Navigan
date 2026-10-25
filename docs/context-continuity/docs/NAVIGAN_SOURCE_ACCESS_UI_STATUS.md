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
