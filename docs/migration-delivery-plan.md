# Self-managed Kubernetes to EKS migration delivery

First pilot: selected RetailFlow workloads and confirmed dependencies. Full-cluster migration remains a separate mode in the same workflow. Production deployment is not part of this increment.

## Delivery tracker

| Increment | Status | Acceptance gate |
|---|---|---|
| 0. Restore Dev target utilities | Operational fix completed in Dev | Fresh target readiness evidence still required before migration |
| 1. Scope and remediation planning workspace | Implemented; Dev validation pending | Select real inventoried resources; save/reload draft; record owners, mappings and evidence; retain assessment behavior |
| 2. Dependency graph and target verification | Pending | Complete reference metadata; detect unresolved dependencies; verify target capacity, storage, ingress, identity and compatible APIs |
| 3. Versioned execution plan and approval | Pending | Approved artifact references; ordered waves; data strategy; rollback and validation checks; changed plan requires reapproval |
| 4. Selected-workload execution | Pending | Durable asynchronous jobs; idempotency, checkpoints, retries and audit; no traffic cutover by default |
| 5. Validation and cutover | Pending | App/data checks pass; explicit traffic switch approval; tested rollback; source retained during observation |
| 6. Full-cluster accounting and retirement | Pending | Every discovered resource classified migrate/recreate/replace/retire; platform replacement verified; retirement separately authorized |

## Increment 1: current behavior

The existing assessment wizard, connector, report and assessment approvals are unchanged. Once an assessment and source inventory exist, its detail screen links to `/migrations/{migrationId}/plan`.

The new workspace contains:

- Scope & target: selected-workload/full-cluster planning modes, readonly assessed source and target, inventoried resource selection, namespace/name filters, treatment decisions and explicit dependency confirmation.
- Remediate: findings with severity filters; per-finding owner, treatment, target mapping, evidence reference and work status.
- Review draft: scope summary and notes. Execution plan generation, target mutation, verification, execution and cutover remain unavailable.

Selected resources define an **execution-scope draft**. They do not narrow the existing namespace assessment or modify its findings. Full-cluster mode does not certify coverage: the existing inventory can exclude system namespaces and cluster-scoped objects. Manual dependency confirmation is explicit because sanitized metadata does not retain all reference names. Neither a stateful workload selection nor a data strategy choice transfers data.

Evidence attachment is not verified remediation. The accepted work statuses are `PLANNED`, `IN_PROGRESS`, and `EVIDENCE_ATTACHED`; users cannot submit `VERIFIED` or `RESOLVED`. The backend remains `ASSESSMENT_ONLY`.

## Persistence and API contract

Apply additive database migration `025_migration_planning_drafts.sql` before deploying the updated Migration Management backend. Older images continue to work with the added column. No existing checksummed SQL migration is changed.

Existing endpoint: `PUT /api/v1/migrations/{migrationId}`. A planning update must contain only `version`, `changeReason`, and `planningDraft`, plus the existing `If-Match` and `Idempotency-Key` headers. Permission remains `migration.edit`, with existing customer access checks. Status must be assessment-ready, submitted, under review, approved, or rejected.

Draft fields:

| Field | Meaning |
|---|---|
| `schemaVersion` | `1` |
| `mode` | `SELECTED_WORKLOADS` or `FULL_CLUSTER` |
| `assessmentVersion`, `inventoryDigest` | Bind draft to the latest report and matching source inventory |
| `resources[]` | API version, kind, namespace, name, treatment and manual dependency flag |
| `remediations[]` | Finding index within that assessment version; owner, treatment, target mapping, evidence reference, work status |
| `dataStrategy` | Undecided, backup/restore, replication or no persistent data |
| `notes` | Planning notes; do not store credentials or secret values |

The server verifies inventory membership, finding indices, duplicate entries, and evidence references. Source nodes cannot have `MIGRATE` treatment. It compares source, target and assessment scope with the stored configuration snapshot used by the assessment. Stale configuration requires reassessment, even if a source inventory digest still matches.

Save increments the migration record version and stores the draft in the migration version snapshot and audit log (`MIGRATION_PLANNING_UPDATED`). It does not change assessment status, score, findings, source/target configuration or connector permissions. Read responses expose `planningDraft`; old rows have `{}`.

Limits: 64 KiB existing request limit, up to 2,000 resource decisions and 500 remediation entries. Large-estate bulk/paged persistence is a later requirement; do not treat this draft as an execution specification.

## Dev validation sequence

1. Review this branch and CI results. Keep the running Prod image and Prod database unchanged.
2. Apply migration 025 using the existing migration runner configured for the **Dev** database. Verify the Dev database ARN/name before any administrative command. The AWS profile alone does not select the database.
3. Deploy the updated Migration Management backend using the existing Dev deployment procedure. The frontend alone cannot enable draft persistence.
4. Pull the branch into the laptop checkout and run the frontend in Dev as usual.
5. Open an existing assessment → Open migration workspace. Select RetailFlow applications and confirm PostgreSQL/Redis plus supporting resources with the application owner.
6. Choose a data strategy; record storage, ingress, identity/secret and node-agent remediation decisions. Save, reload and verify values persisted.
7. Confirm an evidence reference never marks a finding verified, approval remains assessment-only, and unavailable execution actions stay disabled.
8. Validate at 1366×768, 1440×900 and a narrow viewport. Tables may scroll internally; panels and footer must not overlap.

No live cluster or database changes were executed while implementing this increment.

## Requirements for the next backend increments

- Enrich metadata with non-secret reference names; build dependency closure, surface unresolved/external dependencies and require owner confirmation.
- Refresh target readiness from the target connector. Nodes Ready alone is insufficient: scheduling headroom, IP/pod limits, CSI drivers/storage classes, networking/ingress, IAM/RBAC and relevant platform components must be checked.
- Use reviewed Git/Helm/manifests or approved backup artifacts. Sanitized assessment inventory is not deployable content. Recreate secrets through approved secret management; never put secret values into report/draft payloads.
- Use database-native backup/restore or replication as appropriate to PostgreSQL/Redis consistency and downtime needs. Test restore and data checks before cutover; choose Velero/CSI mechanisms only where compatible.
- Bind mutation jobs to platform instance, customer, source registration and target cluster ownership. Dev-created clusters must be acted on only by Dev credentials and the Dev control plane; Prod follows the same code with Prod configuration. Same AWS account is not proof of ownership. Extend this model to cross-account assumed roles later.
- Use a separate authorized executor rather than broadening the read-only assessment connector. Enforce fresh evidence, exact-version approval, durable state, least privilege, audit and explicit rollback/cutover gates on the backend.

Guidance used: AWS Prescriptive Guidance for self-managed Kubernetes → EKS migration (pre-migration checklist and phased migration practices); Kubernetes API compatibility guidance; Velero cluster migration limitations. These are implementation recommendations, not a claim of certification against a single universal container-migration standard.
