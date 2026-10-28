# Source & Discover — approved Option 4

Reviewed 23 October 2026 (Asia/Kolkata).

## Visual target and scope

Approved source: fourth displayed generated design, `generated_images/exec-70664fde-faa4-4875-89e7-90282ca7db3f.png`. Implemented the review journey across the main screen, workload details and collection. All changes are frontend presentation/navigation. Existing migration gates, source analysis behavior, collection/recovery/export requests, permissions and authentication are preserved. Collection scope remains separate from migration execution scope.

## Evidence

Local QA directory: `frontend/.ui-standards/option4-qa/`.

- `comparison.png` places approved reference and rendered implementation together for all three states.
- `main-reference.png`, `workload-reference.png`, `collection-reference.png` are crops of the selected board.
- `main-implementation.png`, `workload-implementation.png`, `collection-implementation.png` are cloud-browser captures of actual React components with synthetic API fixtures.
- Main source crop: 1322 × 607 pixels; child source crops: approximately 706 × 400 pixels. Each implementation capture: 1348 × 926 pixels, desktop CSS viewport at density 1. Images were resized proportionally for comparison; the board has a different aspect ratio, so this is not a pixel-difference claim.

## Comparison and fixes

1. P1: inherited page CSS prevented the compact title/workflow grid. Resolved the conflicting display and workflow button backgrounds. The final main capture shows a compact context row and plain text navigation.
2. P2: inherited margins and grid gaps made the collection view too tall. Removed those gaps in the scoped journey layout. Progress, remaining items and export explanation now appear together.
3. P2: intrinsic grid/flex minimum sizes caused page overflow at 390px. Reset minimum widths while retaining local table scrolling. Rechecked the narrow main and collection states after the fix.
4. Workload details place source definition and images side by side when space permits, with dependencies/checks/technical context collapsed. Back navigation restores the list and focus. Selecting a workload removes list filters from its detail view.

## Required fidelity surfaces

- Typography: Geist Sans and shared platform tokens retained; 20px page title, 17px review heading, compact readable body/table/control text. No image-rendered text is used as UI.
- Layout rhythm: text navigation, inline evidence totals, review checklist, namespace table and bottom Continue action reproduce the approved hierarchy. Child layouts use the same header and tabs.
- Colors: charcoal shell, neutral surfaces, green primary actions, amber repository evidence and blue image coverage. No pale green panels were added.
- Assets: existing Navigan/Deloitte branding and installed Lucide icons reused. No additional raster art is required by these operational screens.
- Copy: counts and statuses derive from response data. Repository candidates do not imply verified deployed revisions. Workspace loading does not imply collection; saved artifacts do not imply target compatibility. The mock's suggestion that source collection must finish before selecting scope was intentionally corrected.

Expected product differences: retained the existing approved platform shell and environment-specific controls. The implementation displays actual application/init-container rows and existing recovery actions rather than the mock's simplified sample rows. Source connection management remains available as a compact disclosure. Screens are responsive adaptations, not a literal reproduction of the board's sample data or fixed aspect ratio.

## Verification

- 70 focused tests pass: discovery, deployment evidence and artifact workspaces. New checks cover namespace navigation without scope mutation, saved/remaining filtering without collection, and registry access review without writes.
- TypeScript and production build pass; 21 pages generated.
- Review, detail and collection checked at 390, 768, 1024, 1280, 1440 and 1920px. Final narrow states have no page-wide horizontal overflow; wide tables scroll locally.
- Browser interactions checked: local navigation, namespace/workload selection, Back navigation, and saved-artifact filtering. Final browser error inspection showed only browser-extension metadata errors, not application errors.
- Live AWS collection/recovery and every authenticated customer state were not exercised. Full accessibility compliance is not claimed.

No actionable P0/P1/P2 findings remain in the reviewed states. P3 follow-up: provider-specific glyph polish can be refined without changing the accepted shell.

final result: passed
