# Latest correction: persistent source access navigation

The user confirmed the preceding frontend release deployed successfully, but the source access link was still unavailable in their workflow. Code inspection found that the only discovery link was nested inside a conditionally hidden progress panel and also depended on discovery action availability and access readiness.

The correction moves Configure source access into the shared Source & Discover page header beside Back to assessments whenever an assessment has a source registration. It remains available after discovery completion and when readiness is already satisfied; the incomplete-setup message refers to that header action. The existing setup page retains source/customer checks and backend readiness requirements. No backend, authentication, connector or infrastructure changes are included.

Validation: 26 focused discovery/setup tests and frontend TypeScript passed. Regression coverage checks the action remains visible while the completed progress panel is hidden and when source access is already ready. Production authenticated visibility still needs verification after this correction is deployed. Prepare a new frontend release plan from the latest branch, then execute that newly prepared plan. Do not reuse the previous executed plan or reinstall the connected connector.

Shared physical connector customer associations remain pending. Broader UI redesign remains on hold.
