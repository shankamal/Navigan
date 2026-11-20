variable "ebs_csi" {
  type = object({
    addonVersion            = string
    controllerRoleArn       = string
    podIdentityAgentVersion = optional(string)
  })
  default = null
}

locals {
  ebs_csi = var.ebs_csi == null ? {} : { storage = var.ebs_csi }
}

# Existing clusters may reference an installed managed agent. Creating an
# agent is explicit so the plan cannot take over a pre-existing add-on.
data "aws_eks_addon" "existing_pod_identity_agent" {
  for_each = {
    for key, config in local.ebs_csi : key => config if config.podIdentityAgentVersion == null
  }

  cluster_name = aws_eks_cluster.this.name
  addon_name   = "eks-pod-identity-agent"
}

resource "aws_eks_addon" "storage_pod_identity_agent" {
  for_each = {
    for key, config in local.ebs_csi : key => config if config.podIdentityAgentVersion != null
  }

  cluster_name                = aws_eks_cluster.this.name
  addon_name                  = "eks-pod-identity-agent"
  addon_version               = each.value.podIdentityAgentVersion
  resolve_conflicts_on_create = "NONE"
  resolve_conflicts_on_update = "PRESERVE"
  tags                        = var.tags

  depends_on = [aws_eks_node_group.this]
}

resource "aws_eks_addon" "ebs_csi" {
  for_each = local.ebs_csi

  cluster_name                = aws_eks_cluster.this.name
  addon_name                  = "aws-ebs-csi-driver"
  addon_version               = each.value.addonVersion
  resolve_conflicts_on_create = "NONE"
  resolve_conflicts_on_update = "PRESERVE"
  tags                        = var.tags
  configuration_values = jsonencode({
    controller = {
      tolerations = [
        { key = "CriticalAddonsOnly", operator = "Exists" },
        { effect = "NoExecute", operator = "Exists", tolerationSeconds = 300 },
        { key = "navigan.io/system-only", operator = "Equal", value = "true", effect = "NoSchedule" },
      ]
    }
  })

  pod_identity_association {
    role_arn        = each.value.controllerRoleArn
    service_account = "ebs-csi-controller-sa"
  }

  depends_on = [aws_eks_node_group.this, aws_eks_addon.storage_pod_identity_agent, data.aws_eks_addon.existing_pod_identity_agent]
}
