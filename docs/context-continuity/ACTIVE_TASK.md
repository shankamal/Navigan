# Navigan — active task (stable recovery entry point)

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

## Current activity

Finish context recovery validation in a fresh Navigan session after review and merge of this documentation checkpoint. No product implementation is authorized by this documentation change alone.

## Next product task — shared EBS StorageClass GitOps

Recover or rebuild the shared EBS StorageClass GitOps workflow for existing Navigan-managed EKS clusters using the approved API-based architecture. The prior review bundle is reported unavailable. Reuse checked-in `navigan-ebs-gp3` and Argo CD templates and governed delivery patterns; do not substitute manual per-cluster installation for the product workflow.

The first validation target and private operational evidence are supplied in existing Navigan project discussion or private execution environment. Verify authorization and identity before runtime action. Earlier production migration API deployment was reported checksum-verified; do not repeat without new evidence and approval.

## Acceptance criteria

- Recover context and inspect existing APIs, repository code, storage templates, GitOps ownership and relevant local review candidates.
- Confirm authorized product base branch, scope and test plan; do not infer base from checkout alone.
- Rebuild reusable candidate through existing API-governed workflow, preserving cloud/distribution abstraction and backward compatibility.
- Run applicable unit, contract, integration and regression checks; report failed or unavailable tests.
- Present diff and test evidence before publication. Obtain separate publishing, merge and deployment approvals.
- After authorized rollout, verify Argo CD sync, intended StorageClass availability, test PVC binding and successful mount. Distinguish source/tests from live validation.
- No unrelated changes, workload migration, production modifications or deployment without applicable authorization.

## Resume gate

A fresh session must report branch/commit, documents read, verified checkpoint, unknowns, task, exclusions and next action. If local review branches or execution access are unavailable, report blocker and request only necessary evidence. Do not substitute another workflow. Update this file, CURRENT_STATE.md and relevant historical checkpoint after each verified milestone.
