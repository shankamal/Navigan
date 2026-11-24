# Navigan — active task (stable recovery entry point)

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
