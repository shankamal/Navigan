# Source discovery: guided frontend layout

## Scope

Presentation and navigation only, following branch commit f4ee14f. Backend routes, request bodies, permissions, migration versions, inventory matching and readiness conditions remain unchanged. Existing source analysis behavior is retained. Merely opening Files & images reads the workspace list; it does not create, collect, recover or export anything.

## User journey

1. **Discovery overview** shows inventory totals, source evidence freshness and direct next actions. Uncompleted source analysis is labeled Not checked instead of presenting a zero-percent coverage score as a completed check. Repository candidates remain separate from image availability and deployed-revision verification.
2. **Workload explorer** contains namespace and image/name filters, the workload navigator, deployment definitions, image evidence, dependencies and checks. Filters are presentation only. Switching views preserves filters and selected workload. Narrow layouts show the workload list first, then details with a Back action and focus return. View checks & actions opens the existing checks section.
3. **Files & images** loads existing workspaces on first opening. Namespace selection explicitly controls collection scope, not migration execution scope. The preparation sequence explains namespace selection, index creation, collection/recovery and export. When a workspace exists, creating another is secondary. Existing collection/recovery/export eligibility and stale snapshot checks remain intact. Collection help is expandable.

The global Continue to migration scope link retains the existing discovery/assessment gate. S3 export is not introduced as another requirement. Collected artifacts do not imply target compatibility.

## Visual verification

Used actual React feature components with synthetic local API fixtures; no live AWS mutation was performed. Overview, Explorer and Files & images were checked at iframe widths 390, 768, 1024, 1280, 1440 and 1920px. Page width did not exceed usable viewport width. Wide image tables retain local scrolling. Tested narrow-screen list-to-detail and Back navigation. Reviewed empty saved-workspace and populated workspace displays. Namespace labels use neutral text instead of error red; active navigation uses charcoal with white text and a green indicator. Original source screenshots supplied by the user grounded the redesign.

## Automated checks

- TypeScript checking passes.
- 67 focused tests cover deployment evidence, source discovery and artifact workspaces, including view navigation, filter retention, unchecked evidence labels, read-only workspace loading and retry after a failed list request.
- Planning regression checks retain the previously confirmed baseline failure for the multi-namespace selected-count text; planning implementation was not modified.
- Production build was run for the final frontend implementation.

Limits: synthetic fixtures do not verify live customer data, collector availability, registry access or every recovery outcome. Full accessibility compliance is not claimed. Live testing should include an existing workspace, pending/failed collection, stale inventory and a read-only identity.
