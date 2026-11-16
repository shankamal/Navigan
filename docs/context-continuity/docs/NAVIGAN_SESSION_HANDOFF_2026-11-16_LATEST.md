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
