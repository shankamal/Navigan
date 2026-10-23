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
