# AWS administrator instructions

Bootstrap package version: **1.1.3**

Run this package only from an authorized administrator workstation in the
intended customer AWS account. Selecting **Customer-managed setup** in Navigan
does not create or change AWS resources.

## Information supplied by the Navigan operator

- Navigan customer ID
- Customer AWS account ID and region
- Navigan Terraform execution-role ARN
- Navigan Environment Lambda validation-role ARN
- Approved EKS cluster role, node role and KMS key ARNs, when they already exist
- A new provisioning External ID generated specifically for this customer

Never reuse another customer's External ID or bootstrap configuration.

## Windows CMD procedure

1. Extract the ZIP into a new directory and open Command Prompt in that
   directory.
2. Select the intended AWS CLI profile and confirm the active identity:

   ```cmd
   set "AWS_PROFILE=<customer-admin-profile>"
   set "AWS_SHARED_CREDENTIALS_FILE=%USERPROFILE%\.aws\credentials"
   set "AWS_CONFIG_FILE=%USERPROFILE%\.aws\config"
   aws sts get-caller-identity
   ```

   Stop if the returned account ID is not the customer account being
   onboarded.

3. Copy `terraform.tfvars.example` to `terraform.tfvars` and replace every
   placeholder. Use a unique provisioning External ID. Set
   `navigan_discovery_principal_arn = null` when the existing discovery role
   must remain unchanged.
4. Initialize, validate and save a plan:

   ```cmd
   terraform init
   terraform fmt -check
   terraform validate
   terraform plan -out=navigan-bootstrap.tfplan
   ```

5. Review the plan. Confirm the account, role names, approved role ARNs, KMS
   key ARNs and resource counts. Reject any unexpected deletion or replacement.
6. Apply only the saved, reviewed plan:

   ```cmd
   terraform apply "navigan-bootstrap.tfplan"
   ```

7. Return the role ARN and completion evidence to the Navigan operator. Transfer
   the provisioning External ID only through the organization's approved secret
   exchange mechanism. Do not place it in email, chat, tickets, or logs.
8. The Navigan operator stores the same provisioning External ID as the raw
   secret value in the Navigan platform account:

   ```cmd
   aws secretsmanager create-secret ^
     --region <platform-region> ^
     --name "navigan/provisioning/<customer-id>/external-id" ^
     --description "External ID for Navigan tenant-bound provisioning" ^
     --secret-string "<provisioning-external-id>" ^
     --tags Key=ManagedBy,Value=Navigan Key=NaviganCustomerId,Value=<customer-id> Key=Purpose,Value=ProvisioningExternalId
   ```

   Do not use JSON for the secret value. Navigan expects the raw External ID.

9. Return to the environment draft, select **Fetch AWS inventory**, choose the
   eligible resources, apply the verified baseline and save the revision.

## Required review results

- Terraform validation succeeds.
- The provisioning trust permits only `sts:AssumeRole`.
- The trusted principals are limited to the exact Navigan Terraform execution
  role and Environment Lambda validation role.
- The trust requires the unique provisioning External ID.
- `iam:PassRole` is limited to the approved EKS roles.
- EC2 instance launches are restricted to the configured AWS region.
- Access to the EKS managed-node-group service-linked role is limited to its
  exact role ARN.
- KMS permissions are limited to approved keys.
- Navigan-created KMS keys allow only the account root and the exact Auto
  Scaling service-linked role required for encrypted EKS worker volumes.
- Discovery can list regional instance-type offerings so the environment
  blueprint can select multiple compatible worker types.
- The reviewed plan contains no unexpected deletion or replacement.

## Sensitive files

`terraform.tfvars` and Terraform state contain sensitive material. Store state
in an approved encrypted backend with locking for production use. For a local
test, restrict access to the working directory and remove local sensitive
artifacts after the bootstrap has been transferred to managed state.

Never send AWS credentials, the External ID, `terraform.tfvars`, Terraform
state, or the saved plan through email, chat, tickets, or application logs.
