# Navigan session handoff — 15 November 2026

## Authoritative recovery point

This handoff supersedes the 12 November 2026 Upgrade & Patching checkpoint for all frontend/UI work completed since then. Preserve older checkpoints for backend execution/governance history, but use this file first when resuming the current Navigan UI work.

### Working contract

- Repository: `shankamal/Navigan`
- Local checkout: `/mnt/b/Langchain_Ai/Navigan-migration-test`
- Active feature branch: `feature/upgrade-patching-ui-approved`
- Latest product-code head before continuity-only documentation updates: `19ea59c57208b6ee0f81d65c6e635bb5abc9deba`
- PROD URL: `https://navigan.click`
- AWS profile: `navigan`
- Region: `ap-south-1`
- Do not merge to `main` unless the user explicitly asks.
- Do not sync DEV unless explicitly requested.
- Do not delete, reset or overwrite unrelated local files.

## Upgrade & Patching — latest accepted UI direction

The Create Upgrade Plan and View Plan experiences were materially refined after the 12 November checkpoint.

### Create Upgrade Plan

Approved design/behavior:

- One compact top-left **Back to Upgrade Centre** control; remove the previous split/duplicated back treatment.
- Plan Type is now:
  - **Full Upgrade** — backend scope `CLUSTER`; includes Control Plane, Node Groups, Managed Add-ons, Validation and IaC Reconciliation.
  - **Targeted Upgrade** — user chooses Control Plane, Node Groups or Managed Add-ons and maps to backend scopes `CONTROL_PLANE`, `NODES` or `ADDONS`.
- **Patching remains a separate top-level capability/tab**, not a replacement name for Targeted Upgrade.
- Selected/unselected Plan Type cards stay plain white. Selection is communicated by the green radio only; no dark, blue or pale-green selected surfaces.
- Cluster/customer/environment/platform/current→target context strip is compact and no longer occupies an oversized panel.
- The read-only **Plan approval / Platform Architect** card was removed from beside Change Reason. Approval remains visible in Plan Summary.
- Version & Component Details continues to use live `/upgrade-options` evidence.
- Workflow Preview now uses the governed 12-stage lifecycle:
  1. Readiness
  2. Plan
  3. Approval
  4. Maintenance Window
  5. Control Plane
  6. Health Gate
  7. Add-ons
  8. Node Groups
  9. Health Gate
  10. Post Validation
  11. IaC Sync
  12. Upgraded
- Targeted plans visually mark non-applicable stages without inventing execution progress.

### View Plan / execution progress

A professional **Execution Progress** tracker is now rendered from actual plan/execution evidence.

It uses:
- `plan.status`
- `plan.planSpec.scope`
- `plan.execution.phase`
- `plan.execution.results`
- `plan.execution.gate`
- `plan.execution.gateHistory`
- `plan.execution.postValidation`
- `plan.execution.iacReconciliation`
- `plan.approvedAt`
- `plan.scheduledFor`
- `plan.execution.startedAt`

Visual states are complete / active / pending / attention / skipped-not-applicable. Do **not** fabricate percentages, ETA or elapsed duration.

Existing governed actions remain unchanged: submit, approve/reject, start approved upgrade, confirm start, validate health & continue, refresh execution, reconcile IaC, refresh reconciliation and apply certified reconciliation.

### Important fixes retained

- Candidate-row Create Plan action now enforces planning permission.
- `SUCCEEDED` plans that still require IaC reconciliation remain visible as In Progress until `IAC_SYNCHRONIZED`.
- Planner discovery-error state keeps actions visible but disables save until live component options are loaded.
- Upgrade workspace candidate test race was fixed.
- No multi-cluster plan was introduced; plans remain per cluster.

## Global Navigan shell — new approved standard

The previous corporate/Deloitte-first workspace header was replaced by a single-line **Navigan global top bar**.

Approved design:

- Full **Navigan** wordmark.
- Only the first **N** is the chosen green circular mark; do not render a separate duplicate N/logo.
- Graphite global bar remains the primary dark identity surface.
- Customer and Environment selectors stay in the **same row**, not a second line.
- Search, notifications and authenticated user/role controls stay on the same row.
- Duplicate Navigan branding was removed from the sidebar.
- Desktop navigation toggle moved into the global bar.

### Global scope context

A persistent workspace-scope context now stores:
- `customerId`
- `environmentId`

Selectors use real active Customer/Environment hooks and persist selection through local storage.

Behavior:
- Customer change resets Environment to All Environments.
- Environment choices are restricted to the selected customer.
- Invalid retained environment values are reset to All Environments.

Important limitation: the scope selectors are functional and centrally stored, but **not every capability API/filter has yet been wired to automatically consume the global scope**. Do not claim global filtering is complete.

Search and notification controls are currently shell UI; do not claim a complete cross-platform search engine or notification backend from this increment.

A role/persona-switcher concept was discussed and approved in principle, but **an effective-role switching implementation was not completed in this increment**. Existing authenticated role permissions remain authoritative.

## Platform-wide capability header — approved Option 3

The user rejected repeated graphite capability title bars because the combination of:
- global graphite header,
- graphite sidebar,
- graphite capability title band

felt visually heavy.

Approved platform standard is now:

1. **Global graphite Navigan bar** — sticky at top.
2. **Cloud-white breadcrumb row** — sticky directly under the global bar.
3. **Cloud-white capability header** — sticky under the breadcrumb.
4. Normal capability content below.

Capability header treatment:
- white/cloud-white surface
- graphite title
- muted description
- subtle bottom border
- restrained shadow only for sticky separation
- neutral secondary actions
- green retained for the primary CTA
- no graphite capability fill
- no pale-green or blue title treatment
- compact behavior on desktop
- mobile/tablet falls back to normal stacked/non-sticky layout to preserve viewport space

This was implemented at the **shared CSS layer** so existing `PageHeading` consumers inherit the pattern, with explicit support for custom variants including:
- Platform Dashboard
- Customers
- Environments
- Clusters
- Migration
- Application Modernization / capability landing pages
- Upgrades & Patching

The Dashboard title is now **Platform Command Centre**.

## Breadcrumb / navigation standard

Breadcrumbs are now route-aware and owned by the global shell rather than shallow `Home > module` text.

Information architecture contract:

- Sidebar = capability navigation.
- Breadcrumb = current location/hierarchy.
- Capability title = current task/screen.
- Tabs/stepper = workflow progression.

Examples:

- `Home > Platform Dashboard`
- `Home > Customers > Customer <id> > Edit`
- `Home > Environments > Environment <id>`
- `Home > Clusters > Cluster <id> > Operations`
- `Home > Migrations > Assessment <id> > Source Discovery`
- `Home > Migrations > Assessment <id> > Source Access`
- `Home > Migrations > Assessment <id> > Migration Workspace`
- `Home > Clusters > Create Cluster`

All intermediate breadcrumb entries are links where a stable parent route exists; the current page is non-clickable.

Known follow-up: labels currently fall back to route identifiers for many object pages. A later refinement can replace IDs with fetched customer/environment/cluster/assessment names where those names are safely available without adding expensive duplicate requests.

## Navigation roles

Role-specific Cloud Engineer vs Platform Architect navigation remains active.

Current direction:
- Cloud Engineer and Platform Architect must not have identical navigation.
- Platform Architect must **not** add Policies & Governance yet.
- Creation should increasingly live inside the owning capability rather than growing permanent sidebar submenus. Existing `Create Cluster` / `Import Cluster` entries still exist in the current engineer navigation and remain a future cleanup item; do not silently remove them without the user's next review.

## Validation evidence

### Upgrade refinement validation

Earlier focused Upgrade validation passed:
- 4 test files
- 38 tests

After the global top bar:
- AppShell: 14/14
- Combined AppShell + Upgrade: 52/52

After the platform-wide white sticky capability header and route-aware breadcrumbs:
- first run: 58/60; two failures were test expectation regressions only:
  - duplicate `Environments` link because breadcrumb added a second valid link
  - Dashboard test expected old `Platform command center` text
- tests were corrected to scope sidebar assertions and use approved title spelling.
- focused rerun: 22/22 passed.
- final regression: **6 files / 60 tests passed**:
  - `tests/app-shell.test.tsx` — 16
  - `tests/dashboard.test.tsx` — 6
  - `tests/upgrade-workspace.test.tsx` — 26
  - `tests/scoped-upgrade-planner.test.tsx` — 9
  - `tests/upgrade-component-scope.test.tsx` — 2
  - `tests/upgrade-active-candidates.test.tsx` — 1
- TypeScript `tsc --noEmit` completed without reported errors before the successful test runs.

## PROD frontend release evidence

### Candidate :72 — global top bar

Prepared from source revision `84d622cdf2c2...`.

- Image tag: `905418045935.dkr.ecr.ap-south-1.amazonaws.com/navigan/frontend:release-84d622cdf2c2-70ccc8d49586`
- Immutable digest: `sha256:d33cea1543871438969e90b725e09cabd27f82b0c389c14c48d54436875dea17`
- Candidate task definition: `:72`
- Prepare release plan: `/var/tmp/navigan-prod-frontend-vectkgm8/release-plan.json`
- Prepare explicitly reported: **Frontend service unchanged**.

The user subsequently showed `navigan.click` with the new global Navigan top bar and said **“ok looks good”**. The retained conversation does not contain the corresponding execute/stabilization terminal output, so use that screenshot as visual evidence only; do not infer the exact running ECS revision solely from this checkpoint.

### Candidate :73 — platform-wide white sticky capability header and breadcrumbs

Prepared from source revision `19ea59c57208...`.

- Image tag: `905418045935.dkr.ecr.ap-south-1.amazonaws.com/navigan/frontend:release-19ea59c57208-f5c42e953b5b`
- Immutable digest: `sha256:7be364b70e460a3d5281fc2d091bbca65afc939ed2512d1a2e6102277e1f4bdb`
- Candidate task definition: `:73`
- Prepare release plan: `/var/tmp/navigan-prod-frontend-dojswylf/release-plan.json`
- Prepare explicitly reported: **Frontend service unchanged**.

After the latest visual review the user said **“much better, but still we need few changes, will continue in the morning.”** The retained conversation does not include the `:73` execute/stabilization output. Therefore:
- the new visual direction is user-accepted as the working baseline;
- the exact currently running ECS task revision remains **unverified from terminal evidence in this handoff**.

Do not rerun a deployment merely to establish continuity. On resume, first inspect the current PROD UI and/or current ECS service task only if needed for the next requested change.

## Current user-accepted design rules

- Cloud White / neutral workspace surfaces.
- Graphite reserved for global shell/sidebar, not repeated capability title bands.
- Restrained Navigan/Deloitte green only for primary actions, selected radio/active indicators and positive status.
- No pale green surfaces.
- No blue selection accents.
- No dark selected Plan Type card.
- English-only labels.
- Compact professional enterprise density.
- Cloud/distribution agnostic language where applicable.
- Migration should remain platform/distribution-neutral conceptually.

## Current stopping point / next morning

User explicitly stopped for the night after reviewing the latest platform-wide header direction and said there are still a few UI refinements to make.

Next session:
1. Do **not** redesign the shell again from scratch.
2. Start from the current global top bar + white sticky breadcrumb/header baseline.
3. Ask for / inspect the specific visual issues the user wants changed only if they are not already visible in the next screenshot.
4. Check several representative capabilities (Dashboard, Customers, Environments, Clusters, Migrations, Upgrades) for:
   - sticky offsets/overlap
   - breadcrumb wording/depth
   - header height/density
   - alignment of title/description/timestamp/actions
   - capability-specific CSS still fighting the shared header
5. Preserve all Upgrade governance behavior and the 60-test regression baseline.
6. Do not merge to main or sync DEV without explicit instruction.

## Local files to preserve

Do not delete/reset unrelated files including previously observed:
- `Navigan-MultiStep Upgrade & Patching.pdf`
- `Navigan_Upgrade_N_Patching.pdf`
- `Navigan_Utility_patch_Upgrade.pdf`
- `Yes.docx`
- `\`
- `frontend/node_modules`
- `navigan-registry-role.json`
- `retailflow-ecr-images.json`
- `retailflow-source-ecr-result.json`

## Resume summary

The authoritative frontend baseline is now the **single-line Navigan global bar + role-specific sidebar + sticky route-aware breadcrumb + cloud-white sticky capability header + existing governed Upgrade & Patching workflow**. The latest product-code head is `19ea59c`; final frontend regression is 60/60. Visual direction is accepted as “much better” but still needs small morning refinements. Exact active PROD ECS revision after candidate `:73` must not be asserted without fresh execution/service evidence.
