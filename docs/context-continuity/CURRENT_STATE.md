# Navigan — current state (stable recovery entry point)

Status: RECONCILIATION REQUIRED. Repository documentation audit: 2026-11-24 (Asia/Kolkata). This record is not live deployment verification or authorization for product changes.

## Verified repository evidence at audit

- Default branch: `main`; observed HEAD `6ce589b9de85e22a86e5cf33cb038ef4b5b5fb41` (before this documentation change).
- Main continuity README begins with an 11 November 2026 override; it links to the 7 November handoff and the final 11 November consolidated daily checkpoint.
- `feature/restore-white-ui-ebs-csi` has a newer README override dated 16 November and additional follow-up entries in its daily starter/checkpoint. Observed HEAD `eb6b1e8fdda876ef32df6ccd4a6f900e4f20deba`. Its README refers to another historical feature branch; do not assume either is the user's active checkout.
- README on inspected storage review branches, migration target discovery branch and EKS readiness branch matches main README. This does not establish identical code or runtime state.
- Main's original root instructions pointed to the 23 October handoff. That is historical, not the default resume point.

## Recovery links

- [Historical kit index](README.md)
- [Main's recorded consolidated checkpoint](docs/NAVIGAN_DAILY_CHECKPOINT.md) — section "11 November 2026 — consolidated end-of-session checkpoint (current override)"
- [Main's referenced handoff](docs/NAVIGAN_SESSION_HANDOFF_2026-11-07_LATEST.md)
- [Master context and approved historical operating contract](docs/NAVIGAN_MASTER_CONTEXT.md)
- [Newer branch index at observed commit](https://github.com/shankamal/Navigan/blob/eb6b1e8fdda876ef32df6ccd4a6f900e4f20deba/docs/context-continuity/README.md)
- [Active task](ACTIVE_TASK.md)

## Current product state

Actual selected development branch and local working tree: UNKNOWN. Latest verified live frontend/backend, DEV/PROD parity and pending product task: UNKNOWN in this audit. No runtime checks performed. Recover relevant branch-specific evidence and reconcile later user-approved milestones before replacing these unknowns. Do not restart older tasks, replay deployments or treat a dated file as proof of runtime state.

## Maintenance contract

Maintain one concise state record on the authorized working branch: last verified date, source branch/commit, evidence links, implementation/test/deployment status separately, relevant decisions/exclusions, blockers and next action. Keep detailed history in the existing kit. When transferring context to main or another branch, review the difference; do not imply feature code or runtime changes were transferred with documentation. Update this record and ACTIVE_TASK.md together at milestones. Mark unverifiable pointers UNKNOWN rather than guessing.
