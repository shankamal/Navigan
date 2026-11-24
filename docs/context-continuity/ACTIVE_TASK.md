# Navigan — active task (stable recovery entry point)

Status: context governance and checkpoint reconciliation; product implementation scope not established by this documentation audit.

## Authorized objective

Improve context recovery, prevent stale handoffs and avoid scope deviation. This documentation-only change is for review. Application code, infrastructure, releases, customer data and existing feature branches are outside scope.

## Next action

Review the documentation change. Identify the actual authorized development branch and reconcile the latest relevant handoffs and runtime evidence. Record the user's next approved product task, acceptance criteria, scope exclusions and verified baseline before implementation. Do not automatically resume October or November work solely because historical files call it current.

## Acceptance criteria

- Root agent instructions do not depend on a hard-coded dated handoff.
- Stable current-state and active-task entries exist; historical links remain available.
- Unknown branch/runtime status stays explicitly unknown until verified.
- New read-only session reports actual branch/commit, files read, checkpoint, conflicts, scope and next action before edits.
- No application changes, further publication, merge or production deployment without applicable approval.

At each verified milestone, replace the active task with the next approved task and record evidence, blockers and next action. Preserve historical details in existing dated handoffs.
