# Navigan engineering and session continuity

Navigan is an existing API-based container management platform. Preserve approved cloud-agnostic and container-distribution-agnostic architecture, established engineering patterns, security boundaries and backward compatibility. The latest authorized user scope governs work. Repository and verified runtime evidence take precedence over assumptions or chat memory.

## Mandatory recovery before development

1. Identify repository, selected branch, HEAD and working-tree status. If the agent lacks access to the actual checkout, state that limitation. Never infer the user's WSL branch from a cloud checkout or default branch.
2. Read `docs/context-continuity/CURRENT_STATE.md` and `docs/context-continuity/ACTIVE_TASK.md` on the selected branch. Use `docs/context-continuity/README.md` as the historical index. If either stable file is missing, report it and use the newest relevant README override as provisional evidence only.
3. Read relevant branch-specific handoffs, sections of `docs/context-continuity/docs/NAVIGAN_DAILY_CHECKPOINT.md` and `docs/context-continuity/docs/NAVIGAN_MASTER_CONTEXT.md`. Do not load all historical material indiscriminately. Follow applicable nested instructions, including `frontend/AGENTS.md`.
4. Compare relevant remote branches and commits read-only when state is stale, missing or contradictory. A newer document is not proof its code is merged or deployed. Do not switch branches, merge code or change authorized scope to resolve drift.
5. Before editing, report selected branch/commit, context files and checkpoint dates, verified task, scope/exclusions, missing evidence and next action. If an essential fact is unknown or conflicts, stop the affected implementation and reconcile or request missing evidence. Do not invent a task.

## Scope, safety and delivery

- Inspect existing code and contracts; reuse APIs, services, components, schemas and templates. No unapproved alternative architecture, unrelated refactoring, bypass scripts or infrastructure changes.
- Preserve user files and uncommitted work. Do not reset, clean, delete files or create another worktree to resume this project. Follow established branching/review practices; obtain authorization for branch changes, destructive operations, publishing, merging and production deployment as applicable.
- Define acceptance criteria and affected files; implement incrementally, run applicable tests, review diffs, and report failures, skipped tests and limitations. A generated or tested change or prepared release is not proof of deployment.
- Verify DEV/PROD separately when relevant; do not assume sync. Historical release commands are evidence, not authorization to repeat cloud operations. Never deploy or modify production resources without explicit approval. Preserve rollback and post-deployment checks.
- For source access tasks, consult `docs/context-continuity/docs/NAVIGAN_SOURCE_ACCESS_UI_STATUS.md` and later relevant evidence. Respect historical holds or exclusions until superseded by verified decisions and user authorization.

## Checkpoint maintenance

After substantive work, update the stable state and active-task records with all changes since the previous verified checkpoint, source commits, evidence, acceptance, limitations, approvals and precise next action. Link to detailed dated handoffs and update existing daily checkpoint/start prompt as appropriate. Preserve historical records; treat superseded current-state labels as historical. Do not claim publication or rollout without evidence. Never record credentials, bearer tokens, presigned URLs or sensitive customer details in public documentation. Follow the agreed review and publication process for documentation updates.
