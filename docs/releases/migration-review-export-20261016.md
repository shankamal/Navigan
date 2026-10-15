# Navigan Migration Intelligence — production release candidate (16 October 2026)

## Release boundary
- Base: current `main`; development source: `codex/migration-intelligent-planning` at commit `8881abb864a74ee816267ea77ebc62f45feae6d2`.
- Scope: Source Planning, Target Assessment, Compatibility, Remediation, read-only Migration Plan preview, Review & Export.
- Non-goals: migration execution, cluster changes, connector upgrade, RBAC expansion, reconciliation, GitOps changes.
- Status: **NOT RELEASE READY. No production deployment is authorized by this document.**
- This branch starts from `main`; migration files have **not** been promoted into it yet.

## Release candidates requiring review

### Frontend
`frontend/src/app/(workspace)/migrations/[migrationId]/plan/page.tsx`, migration-management components, models, services, planning helpers, scoped styles, corresponding frontend tests. Review differences in shared UI, workspace context, and API proxy before inclusion.

### Backend
`src/navigan/modules/migration_management/` planning, source/target assessment, compatibility, evidence, reporting and related tests.
Check `infrastructure/modules/migration-management/template.yaml` and `database/migrations/025_migration_planning_drafts.sql`, `026_migration_target_assessments.sql` for production contract compatibility and existing migration state. Inspect shared cluster-management runtime inventory access; avoid unrelated connector management and cluster mutations.

### Explicitly excluded
`connector/agent.py`; `connector/helm/templates/rbac.yaml`; `migration_connector/`; cluster-connector Helm/system template RBAC; target cluster, working tool gateway, shared Aurora direct modifications, Kubernetes and GitOps deployments. All AWS changes require a separately reviewed change set and rollback.

## Preflight release blockers
1. Review and stage **only** scoped file diffs relative to production `main`, reconcile the one commit on `main` not present in development.
2. Run full frontend build, applicable backend test suites, API contract checks, and relevant database migration tests **on this release branch**.
3. Confirm live production backend Pydantic planning-draft support. Legacy runtime rejects `planningDraft.selectedNamespaces` with HTTP 400; selected-only namespaces must not be lost.
4. Verify backend target-compatibility response shape, authorization, and saved assessment API contracts; frontend fallback is not full backend compatibility.
5. Determine whether schema migrations 025 and 026 are already applied using approved read-only DB migration metadata. Do not rerun them blindly.
6. Capture production ECS/frontend immutable digest, production Lambda alias/version, API Gateway routes, CloudFormation stack parameters and migration rollback strategy (read-only).
7. Do not include connector/RBAC changes or launch target discovery refresh. Existing working utility gateway must remain unaffected.
8. Validate exports contain no secrets, sensitive inventory fields or CSV formula injection. Confirm JSON, CSV and Print/PDF output.
9. Obtain go/no-go approval against exact artifact digests after review. No silent promotion from development branch.
10. After an authorized deployment: smoke-test all six planning stages; confirm legacy utilities, onboarding, environment management and other unaffected pages; rollback on regression.

## Validation seen before branching
Development `8881abb`: TypeScript passed, frontend Vitest 10/10 selected tests passed, Next.js 16.3.4 optimized production build passed. Backend validation was previously 36 tests passing at `d795fa2`; later backend additions and final release branch have NOT had full validation. The user verified the 10-workload compatibility UI; remediation, plan, Review & Export browser acceptance remains pending.

## Rollout principle
Promote and test the isolated release artifacts, not `codex/migration-intelligent-planning` wholesale. No runtime changes from this release preparation alone.
