# Migration workflow UI review — 25 October 2026

## Scope and evidence

The user resumed migration UI improvement after image copying. Review used the nine supplied screenshots and the current branch's frontend components. The collection screenshots show fourteen of sixteen artifacts saved: repository files, seven images and two Headlamp recovery artifacts. Two Job records still require source review. This is collection evidence, not target readiness or successful migration.

This change is frontend-only. Existing API payloads, permissions, readiness checks, source ownership, collection jobs, historical exclusions and target evaluation remain authoritative. No backend, schema, IAM, authentication, connector, application workload or cloud deployment changes are included.

## Journey findings and implemented changes

| Step | Evidence and problem | Change |
| --- | --- | --- |
| 1. Source access setup | `064727`: Back is in the page header while Continue sits at the opposite lower corner. | Both actions share one bottom action bar. Configuration stays in its existing source-access editor. Inventory-only readiness is distinguished from verified access. |
| 2. Source discovery and assessment | `064905`, `064921`, `064935`: large counts, raw timestamps, nested scrolling and navigation separated from operations. | One stable action bar for discovery/assessment and continuation, compact KPI values, readable observation time and a colour resource-composition donut with numeric legend. Full counts and assessment details remain available. The namespace table no longer has an unnecessary fixed-height scrolling area. |
| 3. Choose migration scope | `065305`: a card per dependency will become unwieldy as selection grows. | Associated resources use a searchable, kind-filtered table with ten rows per page. Selected-workload names are expandable instead of determining page height. Save and Continue leads to file checks rather than skipping directly to target selection. |
| 4. Check source files and images | Code review: source access is repeated inside scope, despite a dedicated setup page; Recheck looks like another primary workflow step. | Removed the duplicate access editor from scope. Configuration uses the canonical source-access page. Recheck remains secondary and explains that it refreshes repository/image evidence after inventory or access changes; it does not restart discovery. |
| 5. Collect and export | `065620`, `065635`, `065648`, `065704`: six workspace buttons, mixed image/file/recovery rows, long image strings, and recovery reported as generic copying. | Repository files, Container images and Source recovery have separate category views and resolved counts. Only the selected category's collection action is shown. Refresh/index maintenance and unavailable export operations sit under Workspace options. Collection, export and journey navigation share one bottom action bar. Full image references are expandable; source/provider marks are coloured. Active copy and recovery messages are separate. |
| 6. Target compatibility and review | Code review: assessment, back and review controls are separated across the destination panel; a duplicate Execute placeholder adds noise. | Target assessment and review continuation use the common action bar. Review retains the existing disabled approval gate and removes the redundant Execute button. The main workflow still represents the execution stage. |

## Standards applied

- Preserve the established Graphite/charcoal canvas, deep-green primary actions and Geist typography; use existing typography variables in the new shared components.
- Keep one predictable navigation area per screen. Form submission and per-resource recovery controls remain adjacent to the data they act on.
- Keep historical workspace snapshots and source review controls accessible. Do not treat UI reorganisation as authorization to delete or automatically exclude resources.
- Provide text alongside colour, real labels for searches and selectors, native buttons/links, visible keyboard focus, keyboard dismissal for Workspace options, and existing reduced-motion handling for transfer animation.
- Show determinate percentages only from completed artifact counts or confirmed saved copies. In-flight copies remain indeterminate when byte-level progress is unavailable.
- Keep image collection independent of a pending source recovery. Disable repeat collection while jobs of that category are queued/running and explain unavailable actions.
- Wrap action groups at narrower widths and retain horizontal scrolling only for tables whose columns need it. Paginate large associated-resource sets.

## Verification and limits

122 focused frontend tests passed across source setup, discovery, scope, associated-resource browsing, source connections, deployment evidence and artifact collection/export. Regression coverage includes 125 associated resources, search/kind filtering, source ownership/readiness, preserved scope selections, sequential navigation, image collection during recovery, per-category actions, old workspace retention, failed requests, active-job polling and gated approval. TypeScript and a local production build passed.

Browser-based visual verification is incomplete: the available browser could not reach the local development server. Supplied screenshots ground the findings; neither automated tests nor compilation establish visual acceptance, complete accessibility compliance, or behaviour on every viewport. No fresh authenticated production interaction was performed.

Before production acceptance, inspect the running frontend at 1366×768, 1440×900, 1920×1080, 1024×768 and a narrow mobile viewport. Check sticky action-bar placement, keyboard order, dropdown position, table overflow, reduced motion, the source-access editor and every main/child navigation transition. Keep existing saved artifacts and pending historical reviews intact. Deploy using the established frontend prepare/execute method; no backend rollout is required for this UI change.
