# Navigan AWS customer bootstrap

Run this module once in each customer AWS account before creating an EKS
environment profile.

The module creates:

- `NaviganDiscoveryRole` with read-only inventory and eligibility permissions;
- `NaviganProvisioningRole` with bounded EKS provisioning permissions;
- optionally, recommended least-privilege EKS cluster and node roles;
- optionally, a rotating symmetric KMS key for EKS node-volume encryption.
- optionally, `NaviganClusterInstaller`, a customer-side CodeBuild project
  attached to approved private subnets for API-triggered connector deployment.

It does not create networking resources and it does not grant write access to
the discovery role.

Version 1.2.0 adds the private-cluster connector installer. The installer is
invoked only through the Navigan API, retrieves its short-lived connector
credential directly from customer Secrets Manager, and deletes the temporary
secret after a successful rollout. It does not expose Kubernetes or AWS
credentials to the UI.

Version 1.1.4 adds governed, request-specific names for dedicated EKS cluster
roles, node roles and KMS aliases. Version 1.1.3 included the permissions required for EKS managed node groups to
launch instances in the configured region, verifies the dedicated
`AWSServiceRoleForAmazonEKSNodegroup` service-linked role, discovers regional
instance-type offerings, and creates an EKS volume key policy that permits the
exact Auto Scaling service-linked role to launch encrypted worker volumes.
These permissions remain isolated to the tenant-bound roles.

## Existing resources or Navigan recommendations

Customers may supply approved role and KMS ARNs:

```hcl
eks_cluster_role_arns = ["arn:aws:iam::123456789012:role/ExistingEksClusterRole"]
eks_node_role_arns    = ["arn:aws:iam::123456789012:role/ExistingEksNodeRole"]
kms_key_arns          = ["arn:aws:kms:ap-south-1:123456789012:key/example"]

create_recommended_eks_resources = false
```

If the account has no eligible resources, automatic creation is available only
after explicit confirmation:

```hcl
create_recommended_eks_resources     = true
confirm_create_recommended_resources = true
```

Both values must be supplied after reviewing the Terraform plan. Automatic
creation is disabled by default.

Individual resources can instead be requested with approved names:

```hcl
create_eks_cluster_role = true
eks_cluster_role_name   = "NaviganEksClusterRole-dev"
create_eks_node_role    = true
eks_node_role_name      = "NaviganEksNodeRole-dev"
create_eks_kms_key      = true
recommended_kms_alias   = "alias/navigan-dev-eks"

confirm_create_recommended_resources = true
```

## Required inputs

```hcl
region                           = "ap-south-1"
customer_id                      = "CUS-..."
navigan_execution_role_arn      = "<TerraformExecutionRoleArn output>"
navigan_validation_role_arn     = "<Environment discovery Lambda role ARN>"
navigan_discovery_principal_arn = "<Environment discovery Lambda role ARN>"
external_id                     = "<unique customer/account external ID>"
```

Store the same external ID in the Navigan platform account as a Secrets Manager
secret named:

```text
navigan/provisioning/<customer-id>/external-id
```

The secret value is the raw External ID, not JSON. The Terraform state contains
the sensitive trust policy, so production bootstrap state must use an approved
encrypted backend with locking and tightly controlled access. The External ID
must never be stored in browser storage, logs, cluster records, tickets, or
chat.

## Automatic setup governance

Navigan must not create resources automatically from a read-only discovery
session. Platform-assisted setup requires a separately authorized bootstrap
role and the following workflow:

1. Show the exact proposed resources, region, permissions, and cost impact.
2. Require explicit Cloud Engineer confirmation.
3. Require Platform Architect approval.
4. Generate and validate an immutable Terraform plan.
5. Apply only the approved plan and retain the audit evidence.

Until that bootstrap authorization exists, the UI must direct the customer
administrator to run this module manually.

## Private connector installer

Enable the installer with approved network values:

```hcl
create_connector_installer = true
connector_installer_vpc_id = "vpc-..."
connector_installer_subnet_ids = ["subnet-...", "subnet-..."]
```

The module creates a stable installer security group with no inbound rules.
Add its output to the environment contract so Navigan permits it to reach each
private EKS API endpoint on TCP 443. Navigan starts the installer
through the customer provisioning role and passes only non-secret deployment
metadata plus the ARN of an ephemeral customer Secrets Manager secret.

Add the returned role to the approved EKS environment configuration:

```json
{
  "connectorInstaller": {
    "projectName": "NaviganClusterInstaller",
    "serviceRoleArn": "arn:aws:iam::123456789012:role/NaviganClusterInstallerRole",
    "securityGroupId": "<connector_installer_security_group_id output>"
  }
}
```
