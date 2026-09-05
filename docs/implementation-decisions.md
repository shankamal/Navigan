# Implementation decisions and traceability

Source: `Container_Management_Platform_Customer_Management_Specification_v2.docx`, version 2.0.
The original document is not checked into this public repository. AWS Lambda deployment requested
by the project owner takes precedence over the document's generic Kubernetes packaging suggestion.

## Policies resolved for this implementation

| Topic | Implemented policy |
|---|---|
| Draft completeness | Nonblank name required; contacts and providers may be empty until submission. |
| Submission/activation | Require at least one currently active provider and one PRIMARY contact. |
| Name uniqueness | Trimmed, case-insensitive, global across non-DEACTIVATED customers; enforced by a partial unique index. Deactivated names may be reused with new identifiers. |
| Identifiers | Server-generated `CUS-`, `ONB-`, `CON-`, `REV-` prefixes plus UUID hex; example numeric IDs in the spec are illustrative. |
| Provider codes | Database master initially AWS, AZURE, GCP, OCI. OTHER is not seeded because it is optional. Future codes need no schema change. |
| General updates | PUT replaces name, description and contacts; omitted description becomes null and omitted contacts becomes an empty list. Providers use the dedicated PUT endpoint only. |
| Editable states | DRAFT/REJECTED only, Cloud Engineer only. No APPROVED/ACTIVE change-control API is defined in v2, so these changes are blocked until a separately specified authorized operation exists. |
| Resubmission | `/submit` accepts DRAFT or REJECTED. `/resubmit` additionally exposes REJECTED-only behavior. |
| Terminal transition | ACTIVE -> DEACTIVATED only. SUSPENDED -> DEACTIVATED is not enabled; reactivate first. No hard delete or terminal reactivation. |
| Independent review | Creator or current submitter cannot start review, approve or reject their own customer, including dual-role users. Any other authorized architect in scope may complete the review. |
| Reason/comments | Reason required for reject/suspend/deactivate; both stored in authorized status history and review records. Free text must not contain credentials. |
| Audit access | Full audit endpoint restricted to Platform Architect within scope. Engineers/services can view scoped status and review history; optional integration audit access is not enabled. |
| Optimistic locking | All PUT and lifecycle POST endpoints require If-Match; bare or quoted positive version accepted. Missing/malformed -> 400; stale -> 409. Row locks serialize mutations. |
| Idempotency | Optional for every write, scoped to subject + method/path + key. Canonical validated body and If-Match form the request fingerprint. Exact retries return original status/body. Key reuse with a different fingerprint -> 409. Authorization is checked on replay. |
| Idempotency retention | Durable with no automatic expiry in MVP. No duplicate window is silently introduced; an explicit operational retention policy is required before purging. Stored responses contain contact PII and require the same DB access protection/retention as customer data. |
| Scope | `customerId` is the business tenant identifier. Customer grants and explicit platform-wide claims are issuer-controlled. No arbitrary client-selected tenant header. Authorized onboarding creators can access their own customers while their onboarding entitlement remains active. |
| Duplicate conflicts | Global duplicate-name conflicts intentionally return a generic 409 without disclosing the existing customer identifier or data. |
| Provider dependencies | Injected `ProviderDependencies` interface checked for every removal. Default `NoEnvironmentModule` is valid only before Environment Management exists. Wire a fail-closed dependency adapter before launching that module. |
| Provider deactivation | Master table is changed only by migration/admin process. Submission and activation revalidate provider activity; disabling a provider does not silently remove historical associations. |
| Notification boundaries | Transactional domain event -> EventBridge -> encrypted SQS queue; enterprise notification consumer resolves recipients and retrieves authorized reason/history. No contact details or rejection reason is broadcast on the shared event bus. |
| Retention | No API deletion; append-only audit/history/reviews. Admin retention/PII erasure workflows require separate policy and authorization. |
| Performance | Reads are indexed for IDs, status, creator and provider membership. Substring search scans within scope; add pg_trgm indexes after measuring scale. List fetches at most 100 provider sets; batch aggregation can replace this if profiling warrants. |

## Specification traceability

| Specification requirement | Implementation | Verification |
|---|---|---|
| US-CM-001/002 create/drafts | models.py, service.create, migration customers/contacts | validation, draft and duplicate tests |
| US-CM-003 provider management | ProviderSet, service.update, Repository.replace_providers | invalid-provider rollback, dependency veto, concurrent update tests |
| US-CM-004..009 lifecycle | workflow.TRANSITIONS, service.transition | exhaustive state/role matrix, end-to-end onboarding/rejection tests |
| US-CM-010/011 listing/details | repository scope/list, handler GET routes | customer-scope and membership-filter tests |
| US-CM-012 update | check_edit/check_version, service.update | edit matrix, concurrency and stale version tests |
| US-CM-013..015 operational states | suspend/reactivate/deactivate transitions | end-to-end terminal state tests |
| US-CM-016 history/audit | records endpoint, immutable DB triggers | audit role and trigger tests |
| Section 15 SaaS security | shared.auth, scoped repository, restricted SQL roles | identity forgery, scope, replay, database role tests |
| Section 16 idempotency/concurrency | transaction, advisory key lock, customer row lock | simultaneous updates/creates and action retry tests |
| Sections 18/19 audit/events | service.record, shared.outbox, SAM EventBridge/SQS | audit redaction, outbox transaction and publisher tests |
| Section 20 future modules | interfaces.py and separate schemas/modules | dependency veto test; architecture documentation |
| Sections 21/22 quality | structured logs, metrics, tests, SAM, OpenAPI generator | CI, OpenAPI validation and deployment notes |

## Boundaries requiring deployment validation

This repository provides implementation and deployment configuration, not a claim of production certification.
Validate OIDC claim issuance, real Aurora version/parameter compatibility, VPC connectivity, TLS/secret rotation,
load/SLO targets, event/notification consumers, backup/restore and alarm destinations in the target AWS environment.
