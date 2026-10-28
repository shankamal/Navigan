# Deployment evidence UI refinement — 20 October 2026

## Visual truth and evidence

- Main reference: `/workspace/scratch/629aa0f38b35/generated_images/exec-959b8b94-f227-4e0d-af12-ba3d381dbeaf.png` (1568 × 1003 raster).
- Resolve reference: `/workspace/scratch/629aa0f38b35/generated_images/exec-e5260dd8-775b-4067-b567-f88697101934.png` (1568 × 1003 raster).
- Browser implementation: `/workspace/scratch/navigan-refined-structure.png` (1348 × 926 CSS pixels, 1×); recovery: `/workspace/scratch/navigan-refined-resolve.png` (1363 × 936 CSS pixels, 1×).
- Compared the references and rendered screenshots together. References have no authoritative CSS viewport; comparison uses component hierarchy and proportional spacing rather than treating generated text and shell as literal pixels.
- State: Deployment structure selected, retailflow-api selected, all three regular/init containers shown. Preview-only fixture includes one NOT_FOUND image to inspect the recovery path. No fixture or generated status is included in production code.

## Findings

No remaining actionable P0/P1/P2 findings in the desktop surfaces changed by this increment.

- Typography: existing Navigan Geist Sans retained; 21px workload heading, compact table labels and secondary digest text. Long container names wrap, full references expand/copy. This adapts the mock to the established Navigan shell and narrower content area.
- Layout: namespace navigation and selected workload card, repository strip above the image table, deployment facts below; compact 410px recovery panel with fixed action footer. Existing discovery context and workflow are intentionally retained above this component.
- Tokens: existing green selected/action states, neutral table borders, amber missing-image row and red missing-source panel; text and icons both indicate status.
- Assets: existing branding and Lucide icon system reused; no generated or hand-drawn replacement assets.
- Copy: repository candidate is distinct from verified deployed revision, declared image distinct from runtime digest, and source availability distinct from cache recovery. Recovery requires an evidence-backed digest and remains unavailable for read-only users.

## Comparison history

1. Previous implementation used tall disclosure blocks and placed mapping below images. Replaced with the selected workbench/table composition and compact source strip.
2. [P2, fixed] Resolve wrapped onto two lines in the narrower table action column. Adjusted column proportions and prevented button wrapping. Final structure screenshot confirms the complete one-line action.
3. Reference shows a simple recovery action. Implementation retains required digest selection and access notes for truthful backend behavior; notes are collapsed and main action stays in the footer.

## Interactions and verification

- Browser checked namespace/workload selection, container expansion, missing-image Resolve, digest selection (disabled to enabled action), close and focus restoration.
- Browser error log checked: only browser-extension metadata errors; no application errors observed.
- 61 focused frontend tests passed. TypeScript check and production build passed.
- Recovery network behavior covered with mocked unit tests; no live AWS recovery was executed for this visual refinement.
- Responsive CSS preserves source type, stacks navigator/card below 760px and confines image-table overflow. Mobile browser capture was not performed; desktop was the approved visual target.

## Implementation checklist

- [x] Main workbench and per-container evidence table.
- [x] Compact Resolve panel and fixed actions.
- [x] Preserve backend contracts and permission gates.
- [x] Browser comparison, tests, typecheck and production build.

## Follow-up polish

Optional mobile device review; no further desktop blocking issue identified.

final result: passed
