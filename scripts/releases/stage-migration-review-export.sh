#!/usr/bin/env bash
# Prepare a migration-only release candidate. No AWS commands. No push/deploy.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
CURRENT="$(git branch --show-current)"
EXPECTED="release/migration-review-export-20261016"
[[ "$CURRENT" == "$EXPECTED" ]] || { echo "ERROR: switch to $EXPECTED first (currently: $CURRENT)" >&2; exit 1; }
[[ -z "$(git status --porcelain)" ]] || { echo "ERROR: clean working tree required" >&2; exit 1; }
git fetch origin main codex/migration-intelligent-planning
SOURCE="origin/codex/migration-intelligent-planning"
# Paths that belong to migration workflow only; intentionally excludes connectors,
# cluster-management service, GitOps, RBAC, and unrelated shared UI changes.
paths=(
 "frontend/src/app/(workspace)/migrations/[migrationId]/plan/page.tsx"
 "frontend/src/modules/migration-management"
 "frontend/tests/compatibility-intelligence.test.ts"
 "frontend/tests/migration-graph.test.ts"
 "frontend/tests/migration-legacy-serviceaccount.test.ts"
 "frontend/tests/migration-path-decision.test.ts"
 "frontend/tests/migration-plan-preview.test.ts"
 "frontend/tests/migration-planning-draft-actions.test.ts"
 "frontend/tests/migration-planning-draft-scope.test.ts"
 "frontend/tests/migration-planning.test.tsx"
 "frontend/tests/migration-readiness.test.ts"
 "frontend/tests/migration-recommendations.test.ts"
 "frontend/tests/migration-remediation-handoff.test.ts"
 "frontend/tests/remediation-intelligence.test.ts"
 "frontend/tests/storage-validation.test.ts"
 "frontend/tests/target-capabilities.test.ts"
 "src/navigan/modules/migration_management"
 "infrastructure/modules/migration-management/template.yaml"
 "database/migrations/025_migration_planning_drafts.sql"
 "database/migrations/026_migration_target_assessments.sql"
)
git restore --source="$SOURCE" --staged --worktree -- "${paths[@]}"
echo "Staged allowlisted migration paths only. Review before committing:"
git diff --cached --stat
echo
echo "IMPORTANT: This is NOT a deployable release yet."
echo "Review shared dependencies, backend runtime contracts, migrations, and build/tests."
echo "Do not commit or deploy until all compatibility gates pass."
