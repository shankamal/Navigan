# Approved source discovery workbench — design QA

Reviewed 20 October 2026 against the approved combined Clean Inventory / Focused Evidence Drawer image.

## Evidence and comparison

Reference: the user-approved combined table/drawer image (1487 × 1058 pixels). Browser: 1363 × 936 CSS pixels, density 1; responsive check: 390 × 844 iframe viewport. Both the overview and selected retailflow-api drawer were opened and captured. Full-view and focused drawer comparisons were assembled side by side and inspected; the source was proportionally fitted, not stretched. Different viewport dimensions and the existing application shell prevent a claim of exact pixel identity.

The browser preview imports the actual production screen and styles with isolated representative fixtures. No live AWS operations or credentials were used. A screenshot/preview does not verify the user's live backend.

## Findings and resolutions

- P2, resolved: inherited source-form styles made filters full width and turned evidence tabs/workflow steps into bulky buttons. Added narrowly scoped discovery workbench selectors; the namespace/search toolbar and lightweight tabs now match the approved hierarchy.
- P2, resolved: repeated repository descriptions and expanded container data made the main table too long. Rows now summarize independent Git, registry and runtime evidence; detailed evidence is available in an on-demand drawer.
- P2, resolved: repository and container sections consumed excessive drawer space. Combined repository/artifact identity, tightened dividers, truncated image references, and retained full references and runtime digests in expandable rows.
- P2, resolved: long inventories pushed primary actions away. Evidence rows scroll within a bounded surface, with analysis and workspace actions directly below it.
- P2, resolved: snapshot state could survive an inventory refresh. Local snapshot state now includes the inventory digest as well as workload identity; existing digest checks remain enforced.

## Required fidelity surfaces

- Fonts/typography: existing Geist Sans retained; 24px page heading, 22px drawer heading, 14px workload names and 12–13px evidence metadata. Long identifiers wrap in details and truncate in summaries.
- Spacing/layout: compact identity, six workflow stages, connection strip above discovery, separate completion/review summary, four evidence tabs, full-width table, right drawer and grouped footer actions. Small 3px corners and lightweight separators match the selected direction.
- Colors/tokens: graphite shell, neutral canvas/white surfaces, deep green action/success, restrained amber provenance review. Status words accompany icons.
- Assets/icons: existing Deloitte/Navigan shell assets retained; installed Lucide resource, status and interaction icons used. No generated placeholder illustrations or new branding assets.
- Copy/content: real API values drive production rows; no mock counts, image references or customer records enter production components. Confirmation remains distinct from verified deployed Git provenance; CronJobs without active Pods are neutral, and sanitized inventory is explicitly not deployable.

## Interaction and accessibility verification

Verified namespace/text filtering, all four tabs, drawer opening and closing, Escape dismissal, Shift+Tab containment, focus restoration, expandable container metadata, connection form disclosure and assessment findings disclosure. The drawer makes background content inert and restores body scrolling on dismissal. At 390px its width/clientWidth/scrollWidth were each 390px; no drawer overflow was observed. The table retains local horizontal scrolling on narrow screens.

## Validation and limits

TypeScript and production build pass. Focused evidence/discovery/connections/workspace tests pass (53 tests), including version-protected actions, readonly permissions, stale inventory rejection, source ownership and workspace readiness. Wider-suite comparison found all 25 current failing tests also fail in the unchanged baseline; those legacy planning/approval and route-count failures are outside this frontend change. Browser logs contained extension metadata errors, with no observed application error in the verified interactions.

Accepted differences: existing product shell and responsive viewport sizing; actual data/row counts; scrollable details for long evidence. Minor P3 polish: optional copy affordances and decorative icon choices differ from the generated illustration. These do not block evidence review or migration workflow navigation.

final result: passed
