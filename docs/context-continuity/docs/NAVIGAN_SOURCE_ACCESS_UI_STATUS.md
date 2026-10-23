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
