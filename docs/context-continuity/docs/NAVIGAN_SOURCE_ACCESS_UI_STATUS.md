# Latest source access UI status

Source connection verification and namespace catalogue collection have succeeded in the production test. Detailed inventory and source assessment remain pending.

The assessment action was disabled by the existing source-access readiness requirement, while its setup controls were only reachable later in the workflow. The frontend correction adds a source-access setup child page and a direct discovery link. New-assessment continuation routes through setup when configuration is incomplete. The setup page supports an assessment already at inventory-ready status, validates its source/customer association and excludes unavailable registrations.

This uses existing APIs and the existing repository/registry setup panel. Readiness is not bypassed. Inventory-only discovery remains an explicit user choice, and credentials are not copied between environments. Authentication and backend functions are unchanged by this UI correction.

Local validation passed: 59 focused frontend tests, TypeScript and a production build. This correction has not yet been deployed to production. Deploy only the frontend using the repository's existing prepare/execute release workflow and its newly generated plan. Then open the saved assessment, choose Configure source access, save and verify the required access (or explicitly save inventory-only), return to discovery and run source assessment. No connector reinstall is needed for this UI fix.

Shared physical connector customer associations remain a separate pending capability. Detailed inventory, assessment and artifact collection/export still need production workflow evidence. The broader UI redesign remains on hold.

This status note supersedes older pending-connection guidance for the current test. It deliberately omits infrastructure identifiers and private deployment paths.
