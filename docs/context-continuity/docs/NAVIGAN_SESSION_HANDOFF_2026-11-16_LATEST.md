## Current follow-up — approved System Utilities workspace

User accepted the first generated System Utilities Installed Utilities sample and asked to implement it. This is an existing-repository production UI task, not a separate Sites prototype.

Implemented: dedicated /upgrades/utilities route uses the shared merged header, existing white sidebar and IBM Plex Sans, without unrelated Upgrade Centre/Patching tabs. Four utility views: Installed utilities, Catalogue, Change plans, Maintenance & history. Actor-keyed live inventory, complete authorized fleet list reused from upgrade-plan read model, global customer/environment filtering, cluster selection, search, real recorded metrics, grouped Grafana/Prometheus chart, fresh-evidence health (15 minutes), stale/future/missing evidence Unverified, explicit application-version Not reported. Existing installed-utility draft/review/approval forms and maintenance-date entry points are retained. Catalogue describes current adapters only, with category/search/detail and supported upgrade planning. Argo/connector/unknown utility maintenance is not advertised as a generic upgrade adapter. New registration/installation and execution remain explicitly unavailable; no fake Install/Register buttons or sample live metrics. Change plans show active utility plans; history includes terminal records. Actual plan maintenance starts populate upcoming changes.

Strategy and target architecture: NAVIGAN_SYSTEM_UTILITIES_STRATEGY.md. Future catalogue persistence/registration, installation plans, compatibility/recovery checks and maintenance-gated GitOps execution need separate backend implementation; this source increment does not claim them complete. Prior Headlamp preflight source checkpoint is published as 2d487519410457b5201858fc4730c76a4ede2f71 (same tree as local 4665515), not deployed. Do not rebuild/deploy backend merely for this UI change.

Validation: TypeScript passed; 72 tests across seven frontend suites passed (utility evidence, upgrade workspace/roles/calendar, shared headers, shell and shortcuts); Next production build --webpack passed; git diff --check passed. Fresh health requires READY, Synced, Healthy and a consistent reported chart version. Local fixture preview attempted with real UI components and intercepted services; cloud browser returned upstream connection termination, so visual QA is BLOCKED. Do not call the preview verified or this increment production-ready. No deployment, system-repository write, utility upgrade, main merge or DEV sync.

---

## Current override — 16 November 2026 System Utilities continuation

User accepted the capability-wide UI from c4ce9fb (prepared frontend task :79, digest sha256:43c81e59cb3acca4a37eb5b337e54ac7583371a25b0094f20face8fb065d0beb; exact service revision remains unverified) and requested System Utilities upgrade continuation.

First implementation increment: Headlamp draft creation now reads applications/30-headlamp.yaml from the selected cluster's registered active system repository/default branch using the existing repository-scoped GitHub App read token. It validates the supported Application identity, destination, official chart source and registered values repository/branch, and requires desired chart version to match fresh installed-version evidence. Invalid manifests, drift and GitHub failures block saving. Successful read-only evidence is persisted in utilityEvidence.gitOps and shown in the reviewer panel. Existing plans without this optional evidence remain readable. This snapshot does not establish chart compatibility or guarantee the repository has not changed afterward.

No repository write, PR creation/merge, Argo sync, backend deployment or cluster mutation occurred. Utility execute/refresh remain explicitly blocked. Next implementation: compatibility evidence and an authorized, concurrency-safe GitOps PR workflow, then rollout/health observation; revalidate repository and live versions at those stages. Monitoring remains one shared Grafana/Prometheus chart. Do not treat approval as deployment or dispatch utility plans to the EKS executor.

Checks: 42 backend utility/GitOps/upgrade-plan tests passed. TypeScript passed; 29 frontend upgrade/role tests passed, with the 27-test upgrade workspace suite rerun after adding the repository-evidence assertion. Ruff passed for the new adapter/tests; git diff --check passed. Branch remains feature/upgrade-patching-ui-approved; no main merge or DEV sync. This increment includes backend code and must not be presented as deployed by a frontend-only release.

---

## Current follow-up — capability-wide header, typography and chart standard

User visually accepted the operational Dashboard and requested the same merged sticky header and IBM Plex Sans across all capabilities, a subtle fixed Workspace heading highlight, larger version footer, and a consistent chart palette.

Implemented:
- Shell now owns ONE sticky white breadcrumb/title header for every workspace route except About. Shared PageHeading renders into it through WorkspaceHeading; title/action React context and handlers remain intact, with standalone fallback when no shell exists. Target resets on route changes.
- Included custom headers: customer create/edit, migration source connection, Upgrade Centre/System Utilities/Patching/Maintenance Calendar, and Create Upgrade Plan. Existing shared-heading consumers cover customer/environment/cluster details/forms/reviews, migration discovery/access/planning/workspace, modernization, onboarding and shortcut pages. No duplicate title remains in page content. Mobile uses normal stacked/non-sticky layout.
- Root font contract now IBM Plex Sans with 22px titles, 14px section headings, 13px body/table/control text. Removed Geist stylesheet imports and replaced legacy font overrides/fallbacks, retaining monospace where appropriate.
- Fixed Workspace heading uses a subtle #F4F6F8 neutral surface, fine divider, restrained shadow and muted green left accent. Footer version is 13px/500, slightly taller, with a readable compact version in collapsed navigation. Existing no-visible-scrollbar behavior and keyboard/wheel/touch reachability retained.
- Shared chart-palette.ts defines provider, lifecycle, health and categorical colors. AWS orange #E5A044; Azure blue #4D8FC7; GCP green #63A477; OCI red #C96863. Health/lifecycle use muted green/amber/slate/gray and muted red for blocked/failed. Provider colors never substitute for status semantics.
- Applied shared palette to Dashboard, customer cloud/lifecycle/active charts, environment cloud/lifecycle/active charts, cluster lifecycle/provisioning charts, migration portfolio/readiness/resource/namespace composition/evidence rings, upgrade readiness/stage/component-plan charts. Chart legends use the same tokens as arcs/slices. Metrics and chart calculations are unchanged.

Validation: TypeScript passed; 171 tests across 20 files passed for shared header, charts, shell, Dashboard, customer/environment forms, cluster workspace, source connection/migration/planning and governed upgrades. Added five route-level shared-header assertions afterward; focused 28-test set passed (176 retained tests across the combined set). Production next build --webpack passed. git diff --check passed. Authenticated cross-capability visual review remains pending; no new deployment was executed here.

Release context: preceding product head was 553dd77; user prepared frontend :78 from it, digest sha256:11b48473fdb394c14b5fa4458d08ac24a979c258fb6129e1bd92abea78e20afa, plan /var/tmp/navigan-prod-frontend-7eo_7d5j/release-plan.json. User subsequently said Nice, accepting the displayed Dashboard direction. Execute/stabilization output is absent, so exact running ECS revision remains unverified from terminal evidence.

Next: fetch published feature/upgrade-patching-ui-approved using explicit remote-tracking refspec, fast-forward, verify HEAD equals origin before preparing a NEW frontend candidate. Review Customers, Environments, Clusters, Migration connection/discovery/planning, Upgrade Centre/Create Plan and collapsed sidebar after deployment. Preserve all governance, API data limits, scope handling and previous Dashboard evidence rules. No main merge, DEV sync, backend or EKS mutation.

---

## Current follow-up — approved operational Dashboard and fixed sidebar anchors

This supersedes earlier 16-Nov visual directions below. User approved the Action-first Dashboard sample, then selected calmer colors and IBM Plex Sans matching devopsailab.in. User explicitly requested both sidebar fixes and Dashboard implementation, no visible sidebar scrollbar, and breadcrumb/title merged together.

### Implemented
- Fixed Workspace heading above the menu, no duplicate WORKSPACE group label. Fixed footer displays real application version from frontend/package.json and links to About Navigan; no information-i footer icon. Default width 248px while retained user resizing is respected. Compact menu spacing; visible scrollbar hidden, wheel/touch/keyboard scrolling preserved on short viewports so links are not clipped.
- Dashboard breadcrumb and title/actions render in ONE sticky white header owned by shell. Dashboard heading uses a portal into that header; mobile header stacks normally. No detached title panel, separate sticky breadcrumb strip, or extra title icon.
- Dashboard uses eight capability KPI cards: Customers, Environments, Clusters, Migrations, Cluster Onboarding, App Modernization, Upgrades & Patching, System Utilities. Planned workflows are explicit, and unavailable/incomplete totals are em dashes rather than zero. Cluster count is labelled records, not a fabricated imported/managed split.
- Action-first content: Requires attention; Cluster & environment landscape; provider-colored cloud donut; runtime-evidence health donut; Pending approvals; Migrations in progress; Upcoming Maintenance & Changes with 7/30-day horizon, at most 5 recorded windows and real plan/calendar links. No bar charts, Capability Coverage strip, fabricated trends or made-up operational data.
- Typography: IBM Plex Sans, 22px/600 page title, 14px/600 section headings, 13px body/table, restrained medium-weight KPIs. White cards, subtle dividers, quiet row text links, soft status badges, solid green only for primary action. Provider colors retain AWS orange/Azure blue/GCP green/OCI red with softer chroma; health uses separate semantic colors.
- Actor-scoped React Query read model loads all pages for Customer/Environment/Cluster/Migration lists; failed pagination never yields a misleading first-page total. Customer/Environment workspace filtering applies to data. Migration summaries lack environment association, so environment-scoped migrations show unavailable explicitly.
- Reuses stored per-cluster upgrade plans and platform-components/runtime inventory. No provider upgrade, verification scan, source mutation or automatic execution is triggered by viewing Dashboard. Cached reads are progressive; fleet plan/inventory fan-out remains a performance consideration at scale.
- Runtime health is Ready/Degraded only with fresh observedAt, valid unexpired expiresAt and max 5-minute age; otherwise Unverified. STOPPED/verified zero-node is Paused. Draft requests are excluded from the runtime-health denominator. Missing/stale node counts are not invented.
- Utility KPI uses recorded open utility plans; fresh component inventory is summarized separately. Upgrade candidates and version availability are not fabricated from plan counts. Standalone patch inventory is not exposed by current APIs; KPI supporting text identifies recorded plans.
- Maintenance comes from actual plan scheduledFor or stage windows, excludes terminal/cancelled/rejected/failed plans, retains Submitted/Draft approval state, and uses browser timezone (hydration-safe). No assumed duration or dates. Environment/migration/standalone-patching calendars are not exposed by current APIs and are disclosed.
- Upgrade workspace accepts read-only `?plan=<id>` and `?tab=schedule` links. All existing approval/execution gates remain intact.
- Removed obsolete Dashboard styles/layout module and obsolete summary-query hover prefetch to prevent stale override conflicts/redundant work.

### Checks / rollout
- TypeScript passed; 81 tests across 10 files passed, including scope/pagination, stale/expired/invalid/future health evidence, zero-node behavior, maintenance sorting/windows/approval state, unified header portal, shell, login and governed Upgrade regressions.
- Production `next build --webpack` passed without warnings after correcting the version JSON import. Focused shell/dashboard regression was also rerun after the final presentation fixes.
- Authenticated visual verification remains pending. Cloud Browser previously could not reach this workspace's local preview; do not claim this implementation is visually accepted in PROD.
- Latest user-prepared earlier candidate :77 was from 297a6e6 with digest sha256:f3d2607aa74792aea2311056821a63161553d4bd45cfdd075b5650415355d6ee, plan /var/tmp/navigan-prod-frontend-u1t1frpu/release-plan.json. User subsequently showed the light sidebar and requested this next refinement, but no execute/stabilization output was provided. Do not assert exact running revision without service evidence.
- This follow-up requires a NEW candidate after fetching the published branch with an explicit remote-tracking refspec. Verify HEAD and origin/feature/upgrade-patching-ui-approved match before --prepare; do not reuse older :75/:76/:77 plans.
- No main merge, DEV sync, backend deployment or EKS execution authorized by this UI increment.

---

## Follow-up — sidebar recovery, new menu and full-width Dashboard header

This follow-up supersedes the Dashboard-only sidebar trial below. User supplied PROD screenshot with dark sidebar and requested a new sidebar IA, followed by a full-width white console title strip instead of a card/panel.

- Root cause: legacy `background: #1c222b !important` and selected-item important graphite fills beat the pilot styles. Removed those important legacy fills; a shared `light-navigation` shell class now owns sidebar styling across routes, including mobile expanded state.
- Sidebar: white surface, IBM Plex Sans 13px labels, muted 10px uppercase group labels, pale blue selection and green left marker matching the newly supplied menu. Labels can wrap. Collapsed navigation, resizing, keyboard focus and role filtering remain supported.
- New groups: Workspace (Overview, My Work), Resource Management (Customers, Environments, Clusters), Migration & Modernization (Migration, Application Modernization), Platform Maintenance (Upgrades & Patching, System Utilities), Operations & Observability (Monitoring & Health, Jobs & Activity), Settings (Settings & Help).
- Monitoring & Health / Jobs & Activity are visible non-clickable Planned entries because corresponding capability workflows do not exist yet. Do not claim those features were implemented.
- My Work is a permission-filtered shortcut page, not a new assignment/queue engine. Architect review links remain accessible there; engineers do not gain review permissions. Create/import links removed from permanent sidebar; existing capability routes remain intact. Cluster onboarding informational link remains under My Work.
- System Utilities has `/upgrades/utilities`, opening the existing UpgradeWorkspace utilities tab; it has its own selected navigation state.
- Settings & Help links to About and explains existing workspace preferences; no administrative settings backend added.
- Dashboard breadcrumb/title form a full-width continuous white strip under the global bar. Body content retains 20px gutters. Header stays sticky on desktop, uses a subtle bottom divider without card border/shadow/rounded corners, and stacks normally on narrow viewports. Other capability content themes are unchanged.
- Published pilot was `ff5ceb0` (same tree as local `4814ab3`). User prepared correct candidate `:75`, digest `sha256:01491906722e764d11764498efb7dc4474c734ccf77f2172607cfd50e7347dc0`, plan `/var/tmp/navigan-prod-frontend-tsce6op7/release-plan.json`. New screenshot proves updated title styling but execute/stabilization output remains absent; do not assert exact live ECS task.
- Follow-up validation: TypeScript passed; prior 67-test set passed; 30 focused tests passed including permission-filtered My Work and direct utilities entry (71 retained tests total across the combined set). Production build passed. Local visual verification is still unavailable from Cloud Browser; authenticated visual acceptance awaits deployment.
- Next: publish this follow-up, update WSL checkout, prepare a NEW frontend candidate from the new source commit and execute only its printed plan after checking source/digest. Do not reuse the older :75 plan for these changes. No main merge, DEV sync, backend or EKS changes.

---

# Navigan session handoff — 16 November 2026

## Current increment

Branch: `feature/upgrade-patching-ui-approved`. This supersedes the 15-Nov UI resume task only; retain that handoff for governed Upgrade behavior and deployment evidence.

User requested removal of the post-login lifecycle animation, Customer/Environment selectors moved right immediately before Search, Dashboard title/description at the left panel inset, and a one-capability theme trial based on https://devopsailab.in/.

Implemented:
- AuthGate renders authenticated workspace directly; LoginForm no longer marks the lifecycle intro pending. About Navigan remains available separately. Authentication checks and redirects remain enforced.
- Global scope group owns the flexible left spacer; Search follows immediately, preserving selector logic and customer/environment cascade.
- Dashboard-only theme uses bundled IBM Plex Sans (400/500/600), white sidebar, 13px menu/body, 22px semibold title, 14px section headings, white panels with neutral borders and a #F4F5F7 canvas. Active navigation uses #238408 with white text.
- Dashboard title icon/gutter removed visually; title/description start at the 14px panel inset. Existing sticky header and responsive behavior retained.
- Trial selectors are scoped to `.app-shell.dashboard-shell`; other capability themes remain unchanged pending user review. Existing menus, role permissions, API data and Upgrade governance retained.

Live reference was inspected in Cloud Browser. Confirmed computed IBM Plex Sans, 13px navigation, 22px/600 page heading, white sidebar and #F4F5F7 body. Only theme/density is borrowed; prototype sample data, extra menus and concept features are not copied.

## Validation and rollout

Validation: TypeScript passed; 66 retained tests across 7 files passed (auth entry routing plus the prior 60-test shell/dashboard/upgrade set). An additional 24 temporary fixture-render checks also passed and were removed after use. Production `next build --webpack` passed, including TypeScript and static page generation. `git diff --check` passed. Cloud Browser could inspect the live reference but could not reach the local fixture preview (`ERR_CONNECTION_REFUSED`); no local visual acceptance is claimed. No PROD deployment, main merge, DEV sync, backend change or EKS operation is part of this increment. Authenticated PROD visual acceptance is pending. New font dependency requires refreshing frontend dependencies before local validation.

## Next step

Review Dashboard pilot at desktop and narrow widths, test direct login/dashboard transition, selector cascade, sticky header, sidebar collapse/resize, keyboard focus and navigation to another capability. Apply theme to remaining capabilities only after user approves the Dashboard trial.
