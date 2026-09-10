# Cluster Management: API-first Terraform provisioning

This module consumes an immutable, approved Environment Management baseline. It does not let callers
replace network, security, IAM, or encryption references in a cluster request. Every request pins both
`environmentId` and `environmentApprovedVersion`; plan and apply re-check that the customer and environment
are still `ACTIVE` and that the pinned version remains approved.

## Trust boundary and workflow

All interactive and integration clients use the same path:

`UI / ServiceNow / client -> Cognito/OIDC token -> API Gateway JWT -> Cluster Lambda -> CodeBuild Terraform runner -> customer role`

No browser invokes Terraform, CodeBuild, STS, or a customer cloud API. CloudFormation/SAM deploys only the
Navigan control plane. Terraform is the only customer-resource provisioner.

| State | Actor | API action | Result |
|---|---|---|---|
| DRAFT | Cloud Engineer | create/update | Pins the ACTIVE environment's approved version |
| DRAFT/REJECTED | Cloud Engineer | submit | SUBMITTED |
| SUBMITTED | Platform Architect | review | UNDER_REVIEW |
| UNDER_REVIEW | Platform Architect | approve/reject | APPROVED/REJECTED |
| APPROVED/FAILED | Platform Architect | plan | Asynchronous PLAN_RUNNING, then PLAN_READY/FAILED |
| PLAN_READY | Platform Architect | apply | Applies the exact encrypted plan hash, then ACTIVE/FAILED |

The author cannot review their own request. A failed execution must be planned again; a possibly stale plan
is never reused. S3 versioning, customer-managed KMS encryption, state locking, immutable request versions,
status history, and audit records are enabled.

## Customer prerequisite

The customer administrator installs `terraform/bootstrap/aws-provisioning-role` once. Supply the Navigan
`TerraformExecutionRoleArn` stack output, a unique external ID, only the approved EKS cluster/node role ARNs,
and only the approved encryption key ARNs. The module creates the fixed `NaviganProvisioningRole` with an
ExternalId trust condition and bounded EKS permissions.

Store the same external ID as a SecureString in the Navigan platform account under
`navigan/provisioning/<customer-id>/<account-id>`. The secret value is read only by the isolated runner and is
never returned by the API or written to cluster records, Terraform outputs, or application logs.

## REST API

All writes require `Content-Type: application/json`, `Authorization: Bearer ...`, and a unique
`Idempotency-Key`. Updates/actions also require the latest integer `version` (or `If-Match`).

| Method | Route | Role |
|---|---|---|
| POST/GET | `/api/v1/clusters` | Cloud Engineer / authenticated scoped user |
| GET/PUT | `/api/v1/clusters/{clusterId}` | scoped user / Cloud Engineer |
| POST | `/api/v1/clusters/{clusterId}/submit` | Cloud Engineer |
| POST | `/api/v1/clusters/{clusterId}/review` | Platform Architect |
| POST | `/api/v1/clusters/{clusterId}/approve` | Platform Architect |
| POST | `/api/v1/clusters/{clusterId}/reject` | Platform Architect |
| POST | `/api/v1/clusters/{clusterId}/plan` | Platform Architect |
| POST | `/api/v1/clusters/{clusterId}/apply` | Platform Architect |

EKS `1.0.0` is the first packaged Terraform module. ECS, AKS, GKE, and OKE must be added as separately
versioned modules and runners without changing this lifecycle contract.
