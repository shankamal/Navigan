# Main branch comparison and merge validation — 11 November 2026

## Compared revisions

- Target: main at ac8125e965cb3624c3e7a0686a5e2de9eb244114.
- Reviewed feature head: ef82941de4160395faa63b401a269a99eb2bb9ec, feature/eks-upgrade-readiness.
- Feature contains 45 commits beyond main; main has no unique commits. Merge base equals main. Initial comparison: 80 files, 15,548 insertions and 342 deletions.
- Scope is the completed navigation/upgrade work on this feature branch, including its cumulative history and published continuity kit. Unrelated branches, modified local installer ZIP and unpublished QA changes are excluded.

## What main was missing

| Area | Cumulative implementation being merged |
| --- | --- |
| Navigation | Platform Architect lifecycle menus, expanded role navigation, sidebar resizing, pinned About navigation, guarded feature-branch frontend releases |
| Upgrade Centre | Live inventory/readiness; cloud and distribution identity; customer/account/environment/cluster context; separate saved-plan and available-upgrade lists; filters; component-scope doughnuts |
| Planning UI | Compact scoped planner, fixed rolling-strategy description, maintained shared theme, no redundant header create action, always-visible available upgrades |
| Review UX | Contextual drawer; Close beside Cancel; correct return navigation; requester/reviewer controls; accurate submission/approval metadata |
| Scheduling | Overdue/inactive handling, review/reschedule and renewed approval, month/week calendar and date-specific cluster/utility creation |
| Cluster API | Persisted upgrade plans; explicit control-plane/node/add-on scopes; supported sequential minor-version paths; compatible add-on prerequisites; reviewed per-hop windows and manual execution |
| Utilities | Reported inventory and official target catalogue, persisted drafts/review; execution remains disabled |
| Authorization | Narrow engineer planning/execution privileges, architect approval, legacy-claims compatibility, explicit authorized architect self-approval and recorded approval proof |
| Identity | Profile/Cognito actor-name resolution; original audit actor IDs retained |
| Database/infrastructure | Additive migrations 029–033, scoped runtime grants, IAM/read policies, JWT routes, SAM reconciliation contract |
| Release safeguards | Scoped backend/readiness/role helpers, production baseline/drift checks, packaged dependency verification and read-only review diagnosis |
| Continuity | Consolidated implementation, rollout evidence, limitations and tomorrow's resume instructions |

## Validation results

| Check | Existing main | Feature implementation |
| --- | --- | --- |
| Backend pytest | 1,990 passed, 25 skipped; 1 existing SAM source-contract failure | 2,083 passed, 25 skipped |
| Frontend Vitest | 470 tests in 55 files passed | 519 tests in 63 files passed |
| TypeScript | Passed | Passed |
| Prettier | Passed | Passed |
| Next production build | Passed | Passed |

The existing main failure is a stale migration-management template hash in infrastructure/sam-reconciliation-contract.json. The feature's reconciled contract passes the complete backend suite. Baseline main was tested from an archived tracked-file snapshot, without switching or clearing the user's working tree. Candidate application sources match the published feature, except the whitespace-only correction below; local unrelated files are excluded from publication.

## Corrections required by the merge review

- Previous GitHub backend CI failed nine release-package tests because Git rejected the copied /tmp/source repository ownership. Trust only that exact disposable path inside the test container; never disable ownership checks globally with a wildcard.
- Fetch full history in the backend test job so pinned reviewed production commits remain available to git show in a clean CI checkout.
- Remove one extra trailing blank line in upgrade_paths.py. No runtime behavior changed.
- Focused CI-wrapper/release tests after the correction: 86 passed. Scoped path/release tests after whitespace correction: 30 passed. Shell syntax check passed. GitHub CI must verify the final pull-request head before merge.

## Limits and production boundary

- Twenty-five local database integration tests require disposable PostgreSQL and are skipped locally. GitHub's containerized backend job runs those against its temporary database. This environment has no Docker/SAM CLI; use the actual GitHub jobs for those checks.
- Local browser launch was attempted and failed on Chromium socket/ownership isolation (socket Operation not permitted); fresh authenticated UI verification is not claimed. Passing automated tests does not mean the user has no remaining UI findings.
- Utility execution, automated scheduling and agentic execution are not implemented. Legacy plans require explicit component scope/windows before execution. Architect self-approval still requires effective privilege and scope.
- Merging source does not execute database migrations, alter customer cloud resources or deploy PROD. Existing production evidence and unconfirmed frontend :56 execution remain as recorded in the consolidated checkpoint.
- User deferred remaining product findings until tomorrow. The merge incorporates current implementation; it does not declare those findings resolved.
