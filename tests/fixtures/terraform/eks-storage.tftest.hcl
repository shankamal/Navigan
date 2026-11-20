mock_provider "aws" {}

variables {
  region                     = "ap-south-1"
  provisioning_role_arn      = "arn:aws:iam::123456789012:role/NaviganProvisioningRole"
  external_id                = "test-only"
  cluster_name               = "fixture"
  kubernetes_version         = "1.37"
  endpoint_access            = "PRIVATE"
  vpc_id                     = "vpc-1234567890abcdef0"
  cluster_subnet_ids         = ["subnet-1234567890abcdef0", "subnet-1234567890abcdef1"]
  node_subnet_ids            = ["subnet-1234567890abcdef0", "subnet-1234567890abcdef1"]
  cluster_security_group_ids = []
  node_security_group_ids    = []
  cluster_role_arn           = "arn:aws:iam::123456789012:role/EksCluster"
  node_role_arn              = "arn:aws:iam::123456789012:role/WorkerNodes"
  node_volume_kms_key_arn    = "arn:aws:kms:ap-south-1:123456789012:key/12345678-1234-1234-1234-123456789012"
  node_groups                = []
  tags                       = {}
}

run "storage_is_opt_in" {
  command = plan

  assert {
    condition     = length(aws_eks_addon.ebs_csi) == 0 && length(aws_eks_addon.storage_pod_identity_agent) == 0
    error_message = "Existing cluster configurations must not create storage add-ons."
  }
}

run "new_storage_uses_approved_addons_and_dedicated_role" {
  command = plan

  variables {
    ebs_csi = {
      addonVersion            = "v1.61.0-eksbuild.1"
      podIdentityAgentVersion = "v1.3.10-eksbuild.1"
      controllerRoleArn       = "arn:aws:iam::123456789012:role/DedicatedEbsCsiController"
    }
  }

  assert {
    condition = (
      aws_eks_addon.storage_pod_identity_agent["storage"].addon_version == "v1.3.10-eksbuild.1" &&
      aws_eks_addon.ebs_csi["storage"].addon_version == "v1.61.0-eksbuild.1" &&
      aws_eks_addon.ebs_csi["storage"].resolve_conflicts_on_create == "NONE" &&
      contains(
        [for entry in jsondecode(aws_eks_addon.ebs_csi["storage"].configuration_values).controller.tolerations : try(entry.key, "")],
        "navigan.io/system-only"
      ) &&
      one(aws_eks_addon.ebs_csi["storage"].pod_identity_association).service_account == "ebs-csi-controller-sa" &&
      one(aws_eks_addon.ebs_csi["storage"].pod_identity_association).role_arn == "arn:aws:iam::123456789012:role/DedicatedEbsCsiController"
    )
    error_message = "The storage plan must preserve the approved versions and use the dedicated service account identity."
  }
}

run "existing_agent_is_read_only" {
  command = plan

  variables {
    ebs_csi = {
      addonVersion      = "v1.61.0-eksbuild.1"
      controllerRoleArn = "arn:aws:iam::123456789012:role/DedicatedEbsCsiController"
    }
  }

  assert {
    condition = (
      length(aws_eks_addon.storage_pod_identity_agent) == 0 &&
      data.aws_eks_addon.existing_pod_identity_agent["storage"].addon_name == "eks-pod-identity-agent" &&
      length(aws_eks_addon.ebs_csi) == 1
    )
    error_message = "The existing agent should be read without taking ownership of it."
  }
}
