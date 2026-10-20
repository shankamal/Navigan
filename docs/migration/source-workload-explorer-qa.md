# Source workload explorer QA — 20 October 2026

## Visual truth and state

- User evidence: `/workspace/scratch/629aa0f38b35/upload/image(20261020-070637).png` through `image(20261020-070729).png`; each 1920 × 1080, including browser chrome. These show the repeated status information, four evidence views and long repository index.
- Existing selected workbench visual: `/workspace/scratch/629aa0f38b35/generated_images/exec-959b8b94-f227-4e0d-af12-ba3d381dbeaf.png`, 1568 × 1003.
- Implementation: `/workspace/scratch/navigan-source-workload-explorer.png`, desktop browser, 1348 × 926 CSS pixels at 1×. Recovery: `/workspace/scratch/navigan-explorer-recovery.png`.
- This is a scoped workflow improvement to the existing Navigan screen, not a pixel clone. Browser chrome and different viewport widths are excluded from density comparisons; the card hierarchy and interaction states are compared directly.
- Preview uses isolated fixtures: selected retailflow-api, three containers, a not-found image, an access-required image, dependencies and an empty namespace. No fixture changes are included in production code.

## Findings and comparison history

1. [P1, fixed] Evidence fragmented across four top-level views and an exhaustive file index. One explorer now places deployment definitions, images, dependencies and linked findings under the selected workload. Full file and registry diagnostics open separately.
2. [P2, fixed] Repeated completion/warning panels and a separate action row delayed the useful evidence. One compact completion line remains; actions share the explorer heading. Existing customer, source and workflow context remain available.
3. [P2, fixed] Raw registry table was too narrow in diagnostics. Replaced it with compact expandable image records; full references and registry metadata remain available without clipped columns.
4. [P2, fixed] Access-denied and missing-image rows used the same generic recovery action. Access gaps now enter the existing connection window; missing images retain explicit recovery.

Fonts/tokens: existing Geist Sans and Navigan green/neutral/amber/red styles
retained. Workload heading, section titles and secondary evidence have distinct
weights and sizes; names wrap, digests shorten with full values on expansion/copy.
No new image assets or hand-drawn icons replace supplied branding. Lucide icons
remain consistent with the app. Status has text as well as color. Repository
candidates, runtime observations, source availability and recovery remain separate.

## Validation

- 66 focused frontend tests passed, covering permissions, version protection,
  namespace filtering, empty namespaces, scoped findings/dependencies, dialogs,
  snapshot checks, explicit recovery and once-per-inventory source analysis.
- 71 backend tests passed for deployment-source analysis, migration service and
  artifact recovery, including cross-namespace dependency isolation and rejecting
  analysis from another inventory snapshot.
- TypeScript and production build passed.
- Browser checked namespace selection, empty state, dependency expansion,
  direct connection entry from an access gap, missing-image recovery, on-demand
  diagnostics and dialog close/focus behavior. No live AWS export was initiated.
- Browser console checked; no application error observed (extension metadata
  warnings are unrelated). Desktop visual target verified. Responsive stacking
  and table-local overflow remain in CSS; mobile capture was not performed.

## Implementation checklist

- [x] Consolidate evidence around the selected workload.
- [x] Preserve empty namespaces and all collected Jobs.
- [x] Bind analysis to inventory and scope dependency relationships.
- [x] Preserve recovery/access distinctions and existing permission checks.
- [x] Focused tests, browser review, typecheck and build.

Remaining limits: discovery supports the existing collector resource kinds;
cache recovery still uses one configured source host, and Helm recovery is
partial. No claim of universal artifact recovery or accessibility certification.

final result: passed
