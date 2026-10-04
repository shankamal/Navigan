# Environment Management

Environment Management stores approved reusable infrastructure baselines; it does
not provision Kubernetes clusters. The revised Word specification is version 1.1
at `docs/Navigan_Environment_Management_Specification_v1.docx` (filename retained).

## Structure

- `src/navigan/modules/environment_management/`: Lambda handler, service, repository,
  DTOs and versioned JSON Schemas for AWS/EKS, Azure/AKS, GCP/GKE and OCI/OKE.
- `database/migrations/002_environment_management.sql`: JSONB baselines, configurable
  environment types, immutable versions/reviews/history/audit, indexes and constraints.
- `infrastructure/modules/environment-management/template.yaml`: separate nested
  CloudFormation stack with 21 explicit JWT-protected operations on the shared gateway.
- `frontend/src/modules/environment-management/`: typed services, React Query hooks,
  workflow policy and list/detail/schema-driven create/edit views.
- `docs/environment-openapi.json`: generated Environment API contract.

Existing Customer Management authorization is reused. A scoped Cloud Engineer can
create environments for their assigned customers; `customer_create` is needed only
for the existing customer-creator ownership fallback. Architects review and govern
lifecycle. No Cognito app-client, scope or token-trigger changes are required.

## Deployment order

Use the same backend configuration that now works for Customer Management.
Do not replace real database secret or KMS ARN values with confirmation answers.

```bash
git pull --ff-only
# Use your existing migration-owner connection with TLS verification.
python scripts/migrate.py
# Run with an administrator connection after migrations.
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -f database/bootstrap/roles.sql
sam build --use-container --template infrastructure/template.yaml
sam deploy
```

Docker must be installed and running for container builds. The migration runner is
checksummed and forward-only: never edit migration 001 or drop the working stacks.
Migration 002 adds only the Environment schema. Reapply roles.sql to extend
`navigan_api`, the group granted to the existing application database login.
The Environment Lambda reuses `ApiDatabaseSecretArn`, not `EventsDatabaseSecretArn`.
The existing publisher continues consuming the common outbox and now selects the
correct event source for each module.

After backend deployment, rebuild and redeploy the frontend using the established
scripts and `scripts/frontend/config.env`:

```bash
IMAGE_URI="$(bash scripts/frontend/build-and-push.sh)" && export IMAGE_URI
bash scripts/frontend/deploy.sh
```

Check `docs/frontend-ecs.md` for required image-tag/configuration parameters and
use the image tag produced by the build. Preserve `NAVIGAN_API_ORIGIN` and
`NAVIGAN_API_BASE_PATH=/v1/api/v1` for the existing gateway. Rebuilding the frontend
is required to install the Environment routes and proxy allowlist.

The parent stack now outputs `EnvironmentFunctionName` and
`EnvironmentManagementStackId`. API routes remain `/api/v1/environments`; the
external URL includes the shared `/v1` stage. The handler strips only that exact
stage prefix. All operations require JWT scope `navigan/api` (or the existing
configured JwtScope) and trusted role/customer claims.

## Configuration and lifecycle

Select a customer, then one of their associated supported distributions. Each
selection loads its schema from the API. Drafts can omit mandatory configuration;
submission validates the complete baseline. Common tags Owner, CostCenter and
Environment are Navigan policy requirements. Provider-managed or customer-managed
encryption is supported for AKS/GKE/OKE; the latter requires a key reference.
EKS requires approved KMS node-volume encryption and subnets in two availability zones.
For AWS, Platform Architects can assume a customer-owned `NaviganDiscoveryRole`
with an external ID and fetch a bounded, read-only inventory. The discovery result
populates resource references but never persists the external ID or temporary STS
credentials. Subnet classification uses effective route tables rather than only the
public-IP-on-launch flag. Submission also rejects cross-account IAM/KMS references and
subnet/security-group references that conflict with the selected VPC. Architects still
verify current resource existence, capacity and permissions before approval.

Customer/provider/distribution are immutable. Names are unique case-insensitively
within a customer/provider. Adding new infrastructure fields under `extensions`
requires no database migration. Credentials are forbidden everywhere in configuration;
key-name and credential-pattern checks reduce accidental entry, but administrators
must still ensure arbitrary extension text never contains secrets.

Every write requires `Idempotency-Key`; reuse the key only for the identical retry.
Updates/actions require `version` or `If-Match`. Every mutation increments version
and creates a snapshot. A stale version returns 409. Only DRAFT/REJECTED can be
edited. The workflow supports submit/resubmit, review, approve/reject, activation,
suspension/reactivation and deactivation. Reasons are mandatory for reject,
suspend and deactivate. Detailed history and rejection comments remain visible.

Submission, approval, activation and reactivation require the parent customer to
be ACTIVE. Drafts may be prepared earlier. Removing a customer/provider association
that an environment references returns a dependency conflict instead of orphaning it.
Environment records and their history are not physically deleted.

Cluster consumers must check current environment AND customer status, then pin
`environmentId` and `approvedVersion`, reading the snapshot from
`GET /api/v1/environments/{id}/versions/{approvedVersion}`. Current lifecycle version
may differ from approvedVersion. No provisioning consumer is implemented here.

The immutable approved snapshot is the provisioning contract for stable substrate:
account, region, network, security groups, IAM roles, encryption, connectivity and
mandatory tags. A Platform Setup or Cluster Request owns variable workload intent:
Kubernetes version, control-plane endpoint access, node pools, instance types,
autoscaling bounds and add-ons. A provisioner must persist both the Environment
`approvedVersion` and its Cluster Request version in the cluster record. It must fail
closed if the profile/customer is no longer ACTIVE or a referenced resource cannot be
revalidated; it must never silently substitute resources or resolve an unversioned
"latest" profile. This separation allows many cluster shapes to reuse one approved
environment without losing deterministic, auditable inputs.

Environment domain events are written atomically to the outbox. Their EventBridge
source is `navigan.environment-management`; the existing customer notification rule
is unchanged. Environment notification delivery requires a downstream subscription.

## Diagnostics carried forward

Logs include environment module import, identity validation, configuration validation,
operation, Secrets Manager, database connection, SQL execution and transaction phases.
Request IDs, correlation IDs, elapsed time and safe error locations identify failures.
Configuration bodies, SQL parameters, JWTs and secret values are excluded.
API errors return a correlation ID which the UI displays.

`secret_fetch` ConnectTimeoutError indicates the Secrets Manager network path should
be checked: existing interface endpoint, private DNS, endpoint inbound TCP 443 from
the Lambda security group and matching outbound rules, or the private subnet NAT
route. Reuse the repaired network rather than moving Lambda into public subnets.
Database connectivity uses TCP 5432 and `/opt/certs/global-bundle.pem` from the CA layer.
See [Lambda troubleshooting](lambda-troubleshooting.md).

```bash
aws cloudformation describe-stacks --stack-name YOUR_EXISTING_BACKEND_STACK \
  --region ap-south-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`EnvironmentFunctionName`].OutputValue' --output text
aws logs tail '/aws/lambda/ENVIRONMENT_FUNCTION_NAME' \
  --region ap-south-1 --since 15m --follow
```

Timeouts remain bounded per operation (Secrets Manager connect/read 3s, DB connect
5s, statement 8s, lock 5s). They are not an absolute end-to-end deadline. The stack
includes a Lambda duration alarm at 25 seconds. An AWS deployment is required before
new routes/logs appear; checking code into GitHub does not deploy production.

## Verification and rollout

Tests cover provider validation, unsafe configuration, roles, stage/proxy routing,
concurrent writes, idempotency, cross-customer denial, immutable audit/version history,
all four provider lifecycles, type checking and customer regressions. PostgreSQL
integration tests run in GitHub Actions against a disposable PostgreSQL 16 service.
Run the four-provider onboarding paths in the target environment after deployment.
If reverting application code, retain the additive migration and historical data;
do not drop the schema as part of rollback.
