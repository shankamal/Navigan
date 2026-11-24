# Navigan — current state (stable recovery entry point)

Status: RECONCILIATION REQUIRED. Documentation synchronization baseline verified 2026-11-24 (Asia/Kolkata). This record is not live deployment verification or authorization for product changes.

## Verified repository and checkout evidence

- Repository: `shankamal/Navigan`.
- User-confirmed WSL checkout branch: `feature/restore-white-ui-ebs-csi`, HEAD `eb6b1e8fdda876ef32df6ccd4a6f900e4f20deba` before this documentation change. Remote branch matched that HEAD at audit.
- User-provided working-tree status showed no tracked changes and nine untracked entries. Preserve all existing work. Recheck the actual checkout before changes.
- Approved platform-wide governance was merged to `main` in PR #21, commit `26c54546e5ffa7bcab3331e9b4f7d37077d1ec12`. This synchronization transfers only the four governance documents, not application changes from main.
- The branch README has a 16 November override, and its daily starter and checkpoint contain additional follow-up entries. Older entries mention other branches and tasks; use them as evidence, not current authority.
- User-provided branch listing also shows local review branches for migration target API/UI, production discovery and connector inventory. They were not visible in the connected remote branch listing. Their source differences, publication and deployment status require reconciliation; branch names alone do not prove implementation or rollout.

## Recovery links

- [Branch-specific historical kit index](README.md)
- [16 November handoff](docs/NAVIGAN_SESSION_HANDOFF_2026-11-16_LATEST.md)
- [15 November handoff](docs/NAVIGAN_SESSION_HANDOFF_2026-11-15_LATEST.md)
- [Daily checkpoint and follow-up evidence](docs/NAVIGAN_DAILY_CHECKPOINT.md)
- [Master context and operating contract](docs/NAVIGAN_MASTER_CONTEXT.md)
- [Daily starter and follow-up evidence](docs/NAVIGAN_DAILY_START_PROMPT.md)
- [Active task](ACTIVE_TASK.md)

## Current product state

The checked-out branch is known at the audit baseline. Actual current product scope, most recent accepted UI baseline, deployed frontend/backend revisions, and DEV/PROD parity are not verified in this documentation synchronization. Inspect relevant local review branches and reconcile later user-approved milestones with Git and runtime evidence before replacing these unknowns. Do not restart historical work, replay deployment commands, or infer the current task from branch names.

## Maintenance contract

Maintain one concise state record on the authorized working branch: verified date, source branch/commit, evidence links, implementation/test/deployment status separately, decisions/exclusions, blockers and next action. Keep detailed history in the existing kit. Review differences when transferring context between branches; never imply that code or runtime changes were transferred with documentation. Update this record and ACTIVE_TASK.md together at verified milestones. Mark unverifiable facts UNKNOWN. Never publish secrets or sensitive customer information.
