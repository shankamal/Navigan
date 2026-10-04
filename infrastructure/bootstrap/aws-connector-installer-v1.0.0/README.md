# Navigan private connector installer upgrade

This focused Terraform package upgrades an existing customer account without
taking ownership of its original bootstrap resources.

It reads the existing `NaviganProvisioningRole`, attaches a separate,
installer-only control policy, and creates:

- `NaviganClusterInstallerRole`;
- `NaviganClusterInstaller`;
- a VPC-attached, API-triggered CodeBuild workflow.

The UI never receives AWS credentials, Kubernetes credentials, or connector
tokens. The installer has no inbound listener. It retrieves an ephemeral
credential from customer Secrets Manager, bootstraps Argo CD, connects the
private GitHub system repository, waits for the Argo-managed connector, and
deletes the temporary secret. Argo CD then installs and manages all mandatory
platform utilities on the protected system node group.

The module creates a stable outbound-only
`NaviganClusterInstallerSecurityGroup`. Add its output to the approved
environment configuration as `connectorInstaller.securityGroupId`; each new
cluster then permits that exact group to reach its private Kubernetes API.

Always save and review a Terraform plan before applying it.
