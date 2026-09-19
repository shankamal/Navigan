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
credential from customer Secrets Manager, installs the restricted connector,
waits for rollout, and deletes the temporary secret.

Always save and review a Terraform plan before applying it.
