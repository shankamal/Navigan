# Customer onboarding design QA — 28 October 2026

final result: passed

## Target and evidence

Approved target: user attachment image(20261028-163650).png, the two-column customer profile / contacts layout with readiness inside the right column. Implementation: the actual CustomerForm, AppShell, fonts, logos and styles rendered in an isolated local fixture preview. Only authentication, Next navigation and customer service responses are stubbed in the preview; the harness is not part of the product or deployment. No live API was called.

Evidence: customer-ui-desktop-final.jpg (1363×936 viewport); customer-ui-mobile-dialog.jpg (390×844 iframe); combined full-view and focused form comparisons customer-ui-comparison.png and customer-ui-form-comparison.png. Source is 1487×1058; comparisons scale proportionally, never stretch. The existing application shell has intentionally been retained rather than replaced with the generated shell. This is a structural/visual implementation comparison, not a claim of identical browser dimensions or pixel-perfect raster reproduction.

## Findings, fixes and recheck

- P2, fixed: inherited workspace rules reduced new controls to 32px. Scoped selectors now preserve 40px desktop controls and at least 44px mobile actions. Rechecked computed geometry in the rendered browser.
- P2, fixed: inherited caption rules reduced readiness helper text to 10.5px. The scoped caption token now renders it at 13px; confirmed through computed styles and final screenshot.
- P2, fixed: contact modal initially focused the close button. Opening the editor now focuses the full-name field after the native dialog opens. Confirmed on desktop and mobile; closing returns focus to Add contact.
- Preview-only issue, fixed: the terminal.local fixture needed compiled Tailwind screen-reader utilities and a local fixture UUID. Neither workaround is in production source; the production browser test runs on the existing localhost CI server.

## Required fidelity surfaces

- Typography: existing Geist Sans retained, 28px task title, 18px section headings, 14px inputs/body and readable helper labels. No new font dependency.
- Layout/spacing: two balanced columns, customer profile left, contacts/readiness right, compact provider grid and sticky action bar. Small viewports stack the form and readiness groups. No horizontal overflow in the 390px iframe. A shorter desktop viewport can scroll vertically; the sticky footer stays available.
- Colour: white panels and neutral grey surfaces, charcoal selection outlines. No pale-green cards or provider fills. Existing brand accents, small completion icons and primary action retain deep green.
- Assets: existing bundled AWS, Azure, Google Cloud and Oracle SVGs reused. Existing Lucide icons retained. Unknown provider codes fall back to a cloud icon with their literal name; no unsupported provider is silently dropped.
- Copy/content: approved headings and readiness placement retained. Optional description/email/phone remain optional. The actual character counter is 53 for the sample description, correcting the generated mock's inaccurate 64. “Complete for review” describes completeness, not submission or approval.

## Interaction checks

Browser: select providers; add valid primary and technical contacts; clean subsequent editor; readiness after add; native discard warning dismissed without losing values; fixture draft save clears dirty status; modal focus and mobile dialog fit. Unit tests additionally cover invalid contact email, pending readiness while editing, type changes, removal, normalization, incomplete name-only drafts, editing existing records without changing provider associations, idempotency retry and dirty/unload handling. All 431 frontend tests passed, including 8 customer form tests. TypeScript, production build and formatting passed before the final scoped style/focus refinements; focused tests and TypeScript passed again after those refinements. The repository CI browser acceptance script now exercises the actual Next application using intercepted APIs.

## Limits and accepted differences

Authentication/API persistence in the preview is synthetic; fresh authenticated DEV acceptance remains required after the user deploys. Existing shell density, sidebar labels/truncation and environment-badge logic are retained. Existing brand assets and Lucide check icons differ slightly from generated artwork by design. The leave warning covers links and browser reload/close; framework same-document back/forward navigation is not universally blocked. No backend, database, global theme, auth policy, cloud resource or PROD deployment is changed.

No outstanding P0/P1/P2 findings in this scoped customer form. Follow-up P3: app-wide shell typography can be considered separately if requested.

---

# Upgrade Centre design QA — 5 November 2026

final result: passed

## Target and evidence

The accepted Navigan fleet-upgrade concept is implemented under the approved **Upgrade Centre** name, using the existing graphite navigation, Deloitte green accents and compact workspace density. The guided upgrade-plan concept is retained as the primary follow-on flow.

Evidence: `/upgrades` rendered at 1365 × 936 inside the Navigan application shell; landing state reviewed with summary metrics, multi-provider fleet table, readiness states and upgrade-path drawer. Automated interaction coverage validates tab switching and the first three guided-plan steps. The complete frontend regression suite, TypeScript, formatting and production build passed.

## Findings, fixes and recheck

- P1, fixed: cluster names wrapped too aggressively when the detail drawer reduced table width. Stable fleet-table minimum width and explicit cluster/platform column sizing keep names readable while containing horizontal scrolling within the table region.
- P2, fixed: workspace navigation looked like tabs but exposed generic button semantics. It now uses `tablist`, `tab`, `aria-selected` and `tabpanel` relationships.
- P2, fixed: a preview could imply live provider discovery or execution. A persistent preview boundary and disabled unconnected refresh/approval actions make the implementation status explicit.

## Acceptance and limits

- Navigation and page naming match the approved terminology.
- Information hierarchy remains legible at the inspected desktop viewport.
- Status is never communicated by colour alone.
- Keyboard-visible native controls and semantic tab relationships are present.
- No production cloud mutation or provider execution is exposed by this increment.
- Remaining API-backed discovery, approvals and execution are intentionally deferred and identified in the interface.

No outstanding P0/P1/P2 findings remain in this scoped Upgrade Centre increment.

## 2026-11-07: approved planner and review layout, overdue schedules

Compared the supplied option 1 single-page planner and option 2 review drawer with rendered React components in Chrome at 1363 × 936. The preview uses isolated test inventory and test identities; it is not a production workflow verification.

- Planner: restored persistent workspace navigation, cluster/version strip, three numbered sections, a right-hand checklist/status flow, and sticky save actions. Green ticks follow evidence and form completion. Independent approval remains pending until recorded.
- Review: right-hand drawer retains the plans table context, submitter name/time, component versions/actions, readiness and approval controls. Fixed the clipped component table; cells wrap within the drawer.
- Overdue: the fixture reproduces 7 November 2026, 08:15 Asia/Kolkata. The centre and plan list show an inactive overdue schedule, the approval count excludes it, and the drawer provides a new schedule input instead of approval. Browser interaction confirmed selecting a future time returns the plan to Draft.
- Intentional differences: retained Navigan's shared shell and icons rather than replacing unrelated navigation from illustrative mockups. Actual provider execution order is displayed (control plane, managed add-ons, managed node groups). Readiness in a saved plan is labelled as evidence at creation; execution revalidates it. All supported evidence checks remain available.
- Responsive layout stacks the checklist below the form below 1000px; narrower drawers use 90vw. Desktop visual inspection confirmed readable, unclipped component/version columns and distinct pending/completed states.
- Backend checks enforce the same overdue rule and creator-only rescheduling. Existing approved execution windows are not invalidated when their start time arrives. No schema migration is needed.

Local evidence captures inspected: planner, review drawer and overdue rescheduling. These are isolated test-data previews, not production screenshots. Screenshot binaries are excluded from the code release.
