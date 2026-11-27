# Navigan — current state (stable recovery entry point)

## Checkpoint — 27 November 2026 — Migration Compatibility

This checkpoint supersedes earlier pending Migration compatibility tasks.

### Development baseline
- Branch: feature/restore-white-ui-ebs-csi
- Base commit: 01273c5c1e05b322758a4dab3fede867aee9ac98
- Approved API baseline: bfdcea901168f86e982cd1e86f4e24f5d5572dcf

### Completed implementation
- Corrected source identity evidence contract.
- Automatic refresh of expired incomplete target evidence.
- Workload volume classification and workload-only storage scope.
- Separate scheduling request and placement evidence.
- Network dependency scope evaluation.
- Recovered generalized Kubernetes API discovery.
- Retained approved EBS GitOps GitHub helper.
- Reconciled production repository and service safeguards.
- Preserved target identity, connector ownership and expiry validation.
- Preserved storage mapping invalidation on target change.

### Validation
- Final regression: 626 passed, 1 skipped, 0 failed.
- Skipped integration test requires migrated disposable PostgreSQL.
- Git diff validation passed.
- Existing production Lambda package checksum verified.
- Migration repository source matches verified production source.
- Consolidated candidate is locally implemented and tested.
- Not yet committed, published, merged or deployed.

### Scope boundaries
- Workload migration only.
- Persistent data migration handled separately.
- No backup/restore implementation.
- No connector reinstall or private endpoint modification.
- Preserve API-based, cloud-agnostic architecture.

### Remaining capability backlog
- Advanced scheduling and placement validation.
- CSI provisioning and mounting validation.
- Target networking and connectivity validation.
- Effective workload identity and registry authorization.
- Kubernetes schema and admission validation.
- Consolidated execution readiness.

### Immediate next action
- Review and commit the consolidated Migration candidate.
- Publish through approved GitHub review workflow.
- Prepare a scoped production Migration API release.
- Obtain production deployment approval.
- Deploy and validate the RetailFlow compatibility report.

### Release preparation update
- Migration implementation commit: b77d579547870c2c1fb7c2301435ccf1490c3148.
- PR #29 merged successfully.
- Merge commit: 4cb103a4a7bb3d729e362f4d877c0f569ee8145d.
- Local and remote development branches synchronized.
- Migration API release branch safeguard updated.
- Standalone storage deployment restrictions retained.
- Deployment-specific regression: 57 passed, zero failures.
- Production deployment not yet performed.
- Next action: merge release safeguard PR, prepare and review PROD change set, obtain deployment approval.

---

Checkpoint: 2026-11-24 (Asia/Kolkata). Repository and local branch inventory reconciled; runtime evidence and some local-only code details remain outstanding.

## Verified repository and checkout

- Repository: shankamal/Navigan.
- User terminal confirmed WSL branch `feature/restore-white-ui-ebs-csi`, HEAD `689be50c3291d59c08a9ce3666a884344472270d` after PR #22 documentation-only fast-forward. Remote matched at verification. No tracked changes shown; nine untracked entries preserved. Recheck before edits.
- Governance merged into main in PR #21 (26c54546), synchronized to active branch in PR #22 (689be50). No product or infrastructure changes.
- Main's PR #20 merged governed EBS CSI enrollment at 6ce589b. Active branch has a distinct product history; do not merge main automatically.
- Active branch kit includes 15/16 November handoffs and later follow-ups. This checkpoint supersedes historical resume instructions, not approved architecture or scope exclusions.

## Local review branch evidence (user terminal)

| Branch | Observed HEAD | Scope indicated by commit history |
| --- | --- | --- |
| review/migration-eks-target-api | 2f308e9 | EKS target evidence and compatibility |
| review/migration-eks-target-ui | 544ceda | Assessment of existing and new EKS targets |
| review/prod-migration-target-discovery | b4ac7cc | Code-only production target discovery release |
| review/target-connector-inventory-prod | c35262e | Scoped connector inventory and GitOps ownership release |
| review/existing-eks-storage-enrollment | 74fa70e | Governed EBS CSI enrollment |

First four were not visible in the connected remote branch listing. Preserve local commits. Three-dot comparisons include inherited differences, not just changes in each tip. Publication, full code review and deployment are not inferred from branch names.

## Product checkpoint

- Frontend restoration source exists on active branch; running revision and final UI acceptance not verified here.
- Governed EBS CSI enrollment merged into main; per-cluster state requires runtime evidence.
- Production migration API rollout and checksum verification previously reported in project discussion; connector inventory rollout also reported. No new AWS checks in this task. Exact currently running artifacts and DEV/PROD parity are unknown.
- Migration target UI is a local review candidate; publication and deployment unverified.
- Pending user-directed task: recover or rebuild shared EBS StorageClass GitOps for existing Navigan-managed EKS clusters. Prior review bundle unavailable per discussion. Follow approved API-based design and checked-in templates. See ACTIVE_TASK.md.
- The product implementation base branch must be confirmed independently of the current checkout. Do not replay historical releases.

## Recovery links

- [Active task](ACTIVE_TASK.md)
- [Historical kit index](README.md)
- [Daily checkpoint](docs/NAVIGAN_DAILY_CHECKPOINT.md) — 24 November reconciliation entry
- [16 November handoff](docs/NAVIGAN_SESSION_HANDOFF_2026-11-16_LATEST.md)
- [15 November handoff](docs/NAVIGAN_SESSION_HANDOFF_2026-11-15_LATEST.md)
- [Master context](docs/NAVIGAN_MASTER_CONTEXT.md)

Maintain this concise record and ACTIVE_TASK.md together after verified milestones. Preserve historical records. Distinguish source, tested, published and deployed state. Keep customer identifiers, private runtime evidence, credentials and secrets out of public documentation.
