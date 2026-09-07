# Architecture

API Gateway validates the OIDC access token and passes verified claims to the Customer Management Lambda.
The controller validates DTOs and delegates business behavior to a service; the service uses the workflow,
a scoped repository and a provider-dependency interface. The repository uses parameterized PostgreSQL SQL.
One write invocation owns one database transaction through RDS Proxy; commits occur before success responses.

## Module boundaries

`navigan.modules.customer_management` owns identity, contacts, provider associations and lifecycle.
Its tables live in `customer_management`. `platform` owns shared migration, idempotency and event outbox data.
Environment and Cluster Management must use distinct module directories and database schemas and reference
`customerId`; they must not add account/cluster fields to Customer Management DTOs or customer tables.

The outbox is currently produced by Customer Management; its FK intentionally points to that module's
customer root. If future modules need events unrelated to a customer, introduce a new migration and a
shared aggregate reference contract rather than weakening customer referential integrity implicitly.

## Customer scope and trusted identity

API Gateway must validate issuer, audience, signature, expiry and the configured API scope. Lambda reads
only `requestContext.authorizer.jwt.claims`; it never trusts Authorization contents or X-Role/X-Tenant headers.
Do not expose a Lambda Function URL or grant untrusted principals direct InvokeFunction permission.

| Claim | Meaning |
|---|---|
| sub | Stable subject, max 100 characters |
| roles | Array/JSON-array string/space-separated roles: CLOUD_ENGINEER, PLATFORM_ARCHITECT, SERVICE |
| customer_ids | Array/JSON-array string/space-separated explicit customer grants |
| customer_create | Issuer-controlled true permits Cloud Engineer onboarding and own-customer visibility |
| platform_scope | Issuer-controlled true permits cross-customer visibility for human platform roles only |
| scope/scp | API Gateway checks the configured OAuth access scope; not a replacement for module roles |

Customer ID is the tenant. A scoped user sees only granted customers, plus their own created customers
if still entitled to onboarding. Platform Architects need explicit customer grants or platform_scope.
There is no implicit global access merely because the role is Platform Architect. A tenant user cannot
self-assign creation/global claims; identity administration must keep these claims server-controlled.

Scope is enforced by the service/repository, not PostgreSQL row-level security. Therefore runtime database
credentials are a trusted service boundary and must never be distributed to customer users. Database roles
limit capabilities and separate publisher access, but do not provide per-end-user SQL sessions.

## Transactions and history

All writes lock the customer row and check If-Match before mutation. Provider changes, version increments,
history/review inserts, audit and outbox inserts commit atomically. The name uniqueness index arbitrates
concurrent creates. Idempotency keys acquire a transaction advisory lock before lookup/insertion, preventing
concurrent retries from creating multiple customers. Lock timeouts return a retryable conflict.

Audit snapshots contain only status/version/provider set and changed field names; contact data and free-text
fields are omitted. Authorized status/review records hold reason/comments. Database triggers reject historical
UPDATE/DELETE and runtime roles have insert/select only. No hard-delete API or DELETE privilege on customers.

## Events and notifications

The scheduled publisher takes up to 10 pending rows with `FOR UPDATE SKIP LOCKED`, publishes to EventBridge,
and marks successful entries. Partial failures stay pending with a sanitized error code. A publish can succeed
before a DB commit fails, so delivery is **at least once**. Consumers must deduplicate by payload `eventId`, and
use `customerVersion` to handle reordered events. EventBridge's wrapper ID is not the application dedupe key.
The schedule initially handles 10 events/minute; adjust polling/batch loops/concurrency after measuring volume.
Monitor pending outbox age and failures; never delete failed rows to clear a backlog.

Submission/resubmission, approval and rejection events flow to the notification SQS queue. An enterprise
notification consumer must resolve the Platform Architect audience for submission and the submitting/originating
engineer for decisions. It retrieves customer/status history through scoped service access, includes rejection
reason only in authorized messages, deduplicates events, and acknowledges SQS only after successful delivery.
No email service or user directory was provided, so final message delivery is intentionally an adapter boundary.

## Dependency check integration

Implement `ProviderDependencies.has_dependencies(customer_id, provider_code)` and inject it into the service.
The current bootstrap adapter reports no dependencies because Environment Management is not implemented.
Before deploying Environment Management, replace this adapter with a database-backed check or authenticated
service adapter that fails closed on errors. Use a shared transaction/locking contract between provider removal
and environment creation to prevent a check-then-create race. Active-customer provider changes remain blocked
until an explicit change-control workflow is specified and implemented.

## AWS references

- [Lambda with RDS](https://docs.aws.amazon.com/lambda/latest/dg/services-rds.html): RDS Proxy connection pooling.
- [HTTP API JWT authorizers](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html): verified claims passed to integrations.

## Infrastructure ownership

The parent SAM template composes two nested CloudFormation stacks: `SharedPlatform` owns the shared
HTTP API, JWT authorizer, stage/logs and domain event bus; `CustomerManagement` owns its API Lambda,
18 native API Gateway V2 routes, invoke permissions, outbox worker, notifications, IAM roles and alarms.
Shared resource IDs flow through parent parameters, so modules do not depend on each other's resources.
Updates are orchestrated through the parent. Follow the deployment guide when adding module stacks or
migrating an existing deployment. The current outbox worker is customer-specific despite its shared
code location; future outbox producers need source-aware publishing or filtering before rollout.
