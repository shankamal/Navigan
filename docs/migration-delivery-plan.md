# Navigan migration delivery plan and tracker

Updated: 2026-10-10 (Asia/Kolkata)
Baseline: main at 561eb0584089ed6390d7bf2e21cf9b1f3db13358
Working branch: codex/migration-delivery-plan
Overall status: PLANNED — code analysis complete; implementation not started.

## Goal and scope

Complete a governed self-managed Kubernetes to existing EKS migration, starting with a stateless application in Dev. Navigan must turn assessment findings into target treatments, verify their effectiveness, prepare versioned deployment artifacts, execute approved migration waves, and record validation, cutover and rollback evidence.

The initial supported path remains self-managed Kubernetes to EKS. Other providers and distributions are future extensions. A compatibility score alone is not execution authorization.

Preserve existing discovery, assessment, tenant isolation, RBAC and audit behaviour. New backend APIs and additive database migrations are required; this phase is not UI-only. Do not alter the source connector's read-only permissions. Use a separate scoped target execution identity. Keep secret values outside inventory, reports and execution logs.

Develop and test in Dev first. Production release of Navigan features and execution of a customer's migration are separate milestones. Each requires its own reviewed release or execution plan. Earlier production authorization covered the UI release, not future workload cutovers.

## Current evidence

Inspected migration service, models, handler, repository, connector handler, assessment engine, inventory sanitizer, connector Helm RBAC, migration schema and frontend report/detail controls.

- Service creates ASSESSMENT_ONLY requests; database permits only that execution mode.
- Findings provide resolution steps, validation steps, target treatment and suggested owners.
- AUTOMATED_CHANGE and automationLevel describe recommendations, not an implemented executor.
- Target assessment uses runtime health/freshness and node readiness, not per-finding target-treatment reconciliation.
- Approval transitions enforce role/status/separation of duties; inspected code does not enforce report freshness or unresolved blockers at approval.
- Inventory is sanitized discovery evidence, not a complete deployable manifest backup.
- Live customer findings and target access have not been inspected. The actual production overlap reported on 2026-10-10 is not yet reproduced.

## Tracking rules

States: PLANNED, IN_PROGRESS, BLOCKED, READY_FOR_REVIEW, VERIFIED.
A stage becomes VERIFIED only when acceptance checks have recorded evidence.
For every update record commit/PR, checks run, outcomes, blockers and next step.
Track implementation completion separately from Dev deployment, pilot success and production completion.
When resuming work, read this tracker and reconcile it with current repository and deployment state.
Dates and effort estimates will be added after the actual pilot scope and access are confirmed.

## Milestones

| ID | Milestone | Status | Dependency | Acceptance checks |
| --- | --- | --- | --- | --- |
| M0 | Baseline and pilot definition | IN_PROGRESS | None | Existing migration tests recorded; actual assessment and findings captured without secrets; target EKS and namespace selected; application artifact source and test owner identified |
| M1 | Remediation data model and API | PLANNED | M0 | Versioned tasks reference finding/resource/assessment; owner, target mapping, evidence and exceptions persist; tenant/RBAC/concurrency/audit checks pass |
| M2 | Remediation workspace and report responsiveness | PLANNED | M1 | Create/assign/update tasks through UI; filters and validation evidence visible; no overlapping decision/findings panels at representative widths and zoom |
| M3 | Target validation and readiness gates | PLANNED | M1 | Fresh target evidence reconciles treatments; stale evidence invalidates verification; blockers and exceptions enforced by backend; assessment approval distinct from execution approval |
| M4 | Versioned migration package | PLANNED | M3 | Git/Helm/Kustomize source used; target manifests, mappings, dependency order and diff recorded; immutable package hash; secrets referenced rather than embedded |
| M5 | Preflight and Dev pilot executor | PLANNED | M4 | Scoped target identity; approved package dry-run; one stateless application deployed without source writes; job retries/idempotency/cancellation and application checks demonstrated |
| M6 | Waves and stateful migration support | PLANNED | M5 | Dependencies and wave gates recorded; storage/data method selected per workload; restore/integrity/recovery tests pass; no assumption that manifest deployment transfers data |
| M7 | Cutover and recovery rehearsal | PLANNED | M6 | Traffic-switch plan, authorization, health thresholds and abort conditions defined; rollback rehearsed; stateful write ownership and reverse-sync/recovery strategy explicit |
| M8 | Production release and migration closure | PLANNED | M7 | Dev acceptance signed off; feature release and customer migration approved separately; deployment evidence, observation results, handover and completion recorded |

## Implementation checklist

### M0 — baseline
- [x] Review assessment-to-approval code and identify execution gaps.
- [x] Verify current main against inspected migration code and run targeted regression tests (results below; baseline is not green).
- [ ] Obtain the real report's finding codes and resource references without secrets.
- [ ] Select one low-risk stateless Dev application, target cluster/namespace and artifact repository.
- [ ] Confirm target connectivity, approved deployment identity, test endpoints and operational owners.

### M1–M3 — remediation and readiness
- [ ] Design additive entities: remediation tasks, target mappings, validation runs and approved exceptions.
- [ ] Define stable finding identity using assessment version plus resource identity/code; do not attach verification by display text alone.
- [ ] Task workflow: OPEN -> IN_PROGRESS -> READY_FOR_VALIDATION -> VERIFIED; exceptions require independent authorization and expiry.
- [ ] Separate SOURCE_CHANGE, TARGET_PREREQUISITE, TARGET_MANIFEST_CHANGE, DATA_MIGRATION and EXCLUSION treatments.
- [ ] Define server-verified evidence and manual evidence with reviewer/expiry. A manual checkbox is not technical validation.
- [ ] Preserve original source findings; calculate target readiness separately.
- [ ] Define coverage and artifact completeness checks, not just compatibility score.
- [ ] Enforce freshness, package version and unresolved execution blocker policy in API.
- [ ] Keep assessment approval available for planning; require a separate execution authorization.
- [ ] Test report layout at 1280x720, 1366x768, 1440x900, 1920x1080 and 125%/150% browser zoom; add smaller-width stacking checks. Screen inches alone do not determine viewport size.

### M4–M5 — controlled Dev execution
- [ ] Link application source-of-truth repository/chart and exact revision.
- [ ] Generate target-specific package and readable diff; validate mappings.
- [ ] Use target server-side dry-run and dependency checks; record that dry-run does not test application runtime.
- [ ] Implement durable asynchronous jobs, step logs, locking, retry/idempotency and cancellation.
- [ ] Bind execution approval to target, scope, artifact hash and validation evidence.
- [ ] Check source remains unchanged and target deployment is limited to approved scope.
- [ ] Verify image availability, rollout, probes, configuration references, networking and application tests.
- [ ] Rehearse pilot cleanup/recovery and record evidence.

### M6–M8 — completion
- [ ] Select storage and transfer method per stateful workload with application/data owners.
- [ ] Specify downtime, write freeze or replication strategy, RPO/RTO and integrity checks.
- [ ] Stage dependencies and waves; stop on failed acceptance criteria.
- [ ] Rehearse traffic cutover and recovery including stateful writes.
- [ ] Prepare separate production feature deployment and workload migration runbooks.
- [ ] Record approvals, release/image identifiers, health checks and observation window.
- [ ] Close only after operational handover; source decommissioning requires a separate retention/decommission decision.

## Responsibilities

Assistant: implementation design, code changes, tests, reviewable diffs, tracker updates and deployment/runbook preparation within authorized scope.
Ashok/platform owner: pilot selection, local/AWS execution where credentials are unavailable to the assistant, environment facts and acceptance decisions.
Application/data owners: artifact correctness, functional acceptance, data integrity and recovery requirements.
Independent approver: exceptions and execution authorization according to existing governance.

## Open inputs and blockers

| Input | Needed by | Status |
| --- | --- | --- |
| Actual finding codes/resources and current assessment version | M0 | Pending |
| Pilot application, namespace, artifact source and validation tests | M0 | Pending |
| Existing target EKS readiness/access and scoped executor capability | M3/M5 | Pending |
| Storage/data dependencies, outage limits and recovery objectives | M6 | Pending |
| DNS/traffic ownership and approved cutover method | M7 | Pending |

No production changes or workload migration have been performed under this plan.

## Progress log

| Date | Update | Evidence | Next |
| --- | --- | --- | --- |
| 2026-10-10 | Initial code analysis complete; plan and tracker created | Baseline 561eb05; repository source review, no live migration execution | Finish M0 and specify remediation model/API |

## Definition of done

A selected workload has been remediated, validated, packaged, migrated and accepted in the target under recorded approvals; rollback/recovery is demonstrated; production outcomes and handover are evidenced. Shipping a UI, an assessment score or an APPROVED record alone does not complete this goal.

## Phase 0 baseline check — 2026-10-10

Status: IN_PROGRESS. No application changes, infrastructure changes or live migration actions.

Remote main remains 561eb0584089ed6390d7bf2e21cf9b1f3db13358. Compared the local migration service, models, assessment engine, connector handler, report/detail UI and the failing tests plus connector agent/inventory/RBAC against remote commit contents: exact matches. Tests were run in the working checkout, not an isolated full release checkout; a full release check remains necessary before deployment.

Frontend targeted suite:
- migration-management.test.tsx, migration-approval.test.tsx, migration-proxy.test.ts
- 3 test files, 12 tests passed.

Backend targeted suite:
- Service, models, handler, connector, agent, inventory, source inventory, assessment engine, repository and packaging.
- 103 passed, 3 failed. No live Aurora integration or target execution verified.

Failures requiring resolution:
1. test_refreshes_rejected_assessment_with_connected_source: fixture does not supply sourceClusterId or connector token; service requires one. Verify connected-source and legacy-token behaviours and correct fixture/contract with meaningful regression coverage.
2. test_collects_only_selected_namespaces_and_safe_resources: test forbids Secret/ConfigMap API collection; agent currently collects them for sanitized metadata.
3. test_rbac_is_read_only_and_excludes_sensitive_resources: test expects Secret/ConfigMap/RBAC resources excluded; current chart grants list access. Sanitizer excludes Secret values from reported inventory, but Kubernetes list permission still permits reading full Secret objects. Do not treat output sanitization as metadata-only authorization. Choose collection policy and namespace scope explicitly before changing tests or permissions.

Required pilot intake from Dev:
- Migration ID, assessment timestamp/version, source cluster and selected namespace.
- Finding codes, severities, resource references and target treatments (redact confidential identifiers if needed; do not supply secret values).
- Target EKS cluster/environment and whether runtime inventory is fresh/READY.
- One stateless application; identify PVCs, databases and external dependencies if present.
- Git repository/chart/path and revision used to deploy it.
- Application acceptance endpoint/tests and test owner.
- Confirm target execution access is available without sharing credentials.

Next: resolve baseline discrepancies; obtain pilot intake; record application and target acceptance criteria. Phase 0 is not complete until both code baseline and real pilot readiness are evidenced.
