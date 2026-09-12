data "aws_iam_policy_document" "trust" {
  statement {
    sid     = "NaviganTenantBoundProvisioningAndValidation"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = compact([
        var.navigan_execution_role_arn,
        var.navigan_validation_role_arn,
      ])
    }
    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [var.external_id]
    }
  }
}

data "aws_iam_policy_document" "discovery_trust" {
  count = var.navigan_discovery_principal_arn == null ? 0 : 1
  statement {
    sid     = "AssumeTenantDiscoveryRole"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [var.navigan_discovery_principal_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [var.external_id]
    }
  }
}

resource "aws_iam_role" "discovery" {
  count                = var.navigan_discovery_principal_arn == null ? 0 : 1
  name                 = "NaviganDiscoveryRole"
  assume_role_policy   = sensitive(data.aws_iam_policy_document.discovery_trust[0].json)
  permissions_boundary = var.permissions_boundary_arn
  tags                 = { ManagedBy = "Navigan", Purpose = "ReadOnlyDiscovery", NaviganCustomerId = var.customer_id }
}

data "aws_iam_policy_document" "discovery" {
  statement {
    sid = "ReadNetworkInventory"
    actions = [
      "ec2:DescribeAvailabilityZones", "ec2:DescribeVpcs",
      "ec2:DescribeSubnets", "ec2:DescribeRouteTables",
      "ec2:DescribeSecurityGroups", "ec2:DescribeVpcEndpoints",
      "ec2:DescribeNatGateways", "ec2:GetEbsEncryptionByDefault",
      "ec2:DescribeInstanceTypeOfferings", "ec2:DescribeInstanceTypes",
    ]
    resources = ["*"]
  }
  statement {
    sid = "ReadEksAndRegistryInventory"
    actions = [
      "eks:ListClusters", "eks:DescribeClusterVersions",
      "ecr:DescribeRepositories",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "VerifyIamRoles"
    actions   = ["iam:ListRoles", "iam:GetRole", "iam:ListAttachedRolePolicies"]
    resources = ["*"]
  }
  statement {
    sid       = "VerifyEncryptionKeys"
    actions   = ["kms:ListAliases", "kms:DescribeKey", "kms:GetKeyPolicy"]
    resources = ["*"]
  }
  statement {
    sid       = "ReadServiceQuotas"
    actions   = ["servicequotas:ListServiceQuotas"]
    resources = ["*"]
  }
  statement {
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "discovery" {
  count  = var.navigan_discovery_principal_arn == null ? 0 : 1
  name   = "NaviganReadOnlyDiscovery"
  role   = aws_iam_role.discovery[0].id
  policy = data.aws_iam_policy_document.discovery.json
}

data "aws_iam_policy_document" "eks_cluster_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eks_cluster" {
  count                = var.create_recommended_eks_resources ? 1 : 0
  name                 = "NaviganEksClusterRole"
  assume_role_policy   = data.aws_iam_policy_document.eks_cluster_trust.json
  permissions_boundary = var.permissions_boundary_arn
  tags                 = { ManagedBy = "Navigan", Purpose = "EKSCluster", NaviganCustomerId = var.customer_id }
}

resource "aws_iam_role_policy_attachment" "eks_cluster" {
  count      = var.create_recommended_eks_resources ? 1 : 0
  role       = aws_iam_role.eks_cluster[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEKSClusterPolicy"
}

data "aws_iam_policy_document" "eks_node_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eks_node" {
  count                = var.create_recommended_eks_resources ? 1 : 0
  name                 = "NaviganEksNodeRole"
  assume_role_policy   = data.aws_iam_policy_document.eks_node_trust.json
  permissions_boundary = var.permissions_boundary_arn
  tags                 = { ManagedBy = "Navigan", Purpose = "EKSNode", NaviganCustomerId = var.customer_id }
}

resource "aws_iam_role_policy_attachment" "eks_node" {
  for_each = var.create_recommended_eks_resources ? toset([
    "AmazonEKSWorkerNodePolicy",
    "AmazonEC2ContainerRegistryPullOnly",
    "AmazonEKS_CNI_Policy",
  ]) : toset([])
  role       = aws_iam_role.eks_node[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/${each.value}"
}

data "aws_partition" "current" {}
data "aws_caller_identity" "current" {}

locals {
  autoscaling_service_role_arn = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/aws-service-role/autoscaling.amazonaws.com/AWSServiceRoleForAutoScaling"
}

data "aws_iam_policy_document" "eks_kms" {
  statement {
    sid       = "EnableAccountAdministration"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }
  statement {
    sid = "AllowAutoScalingUseOfKey"
    actions = [
      "kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*",
      "kms:GenerateDataKey*", "kms:DescribeKey",
    ]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = [local.autoscaling_service_role_arn]
    }
  }
  statement {
    sid       = "AllowAutoScalingGrant"
    actions   = ["kms:CreateGrant"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = [local.autoscaling_service_role_arn]
    }
    condition {
      test     = "Bool"
      variable = "kms:GrantIsForAWSResource"
      values   = ["true"]
    }
  }
}

resource "aws_kms_key" "eks" {
  count                   = var.create_recommended_eks_resources ? 1 : 0
  description             = "Navigan EKS node-volume encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.eks_kms.json
  tags                    = { ManagedBy = "Navigan", Purpose = "EKSNodeEncryption", NaviganCustomerId = var.customer_id }
}

resource "aws_kms_alias" "eks" {
  count         = var.create_recommended_eks_resources ? 1 : 0
  name          = var.recommended_kms_alias
  target_key_id = aws_kms_key.eks[0].key_id
}

check "automatic_resource_creation_confirmed" {
  assert {
    condition = (
      !var.create_recommended_eks_resources ||
      var.confirm_create_recommended_resources
    )
    error_message = "Automatic EKS IAM/KMS creation requires confirm_create_recommended_resources = true after reviewing the plan."
  }
}

locals {
  approved_cluster_role_arns = setunion(
    var.eks_cluster_role_arns,
    var.create_recommended_eks_resources ? toset([aws_iam_role.eks_cluster[0].arn]) : toset([])
  )
  approved_node_role_arns = setunion(
    var.eks_node_role_arns,
    var.create_recommended_eks_resources ? toset([aws_iam_role.eks_node[0].arn]) : toset([])
  )
  approved_kms_key_arns = setunion(
    var.kms_key_arns,
    var.create_recommended_eks_resources ? toset([aws_kms_key.eks[0].arn]) : toset([])
  )
}

resource "aws_iam_role" "navigan" {
  name                 = "NaviganProvisioningRole"
  assume_role_policy   = sensitive(data.aws_iam_policy_document.trust.json)
  permissions_boundary = var.permissions_boundary_arn
  tags                 = { ManagedBy = "Navigan", Purpose = "EKSProvisioning", NaviganCustomerId = var.customer_id }
}

data "aws_iam_policy_document" "provisioning" {
  statement {
    sid = "EksLifecycle"
    actions = [
      "eks:CreateCluster", "eks:DescribeCluster", "eks:UpdateClusterConfig",
      "eks:UpdateClusterVersion", "eks:DeleteCluster", "eks:TagResource", "eks:UntagResource",
      "eks:CreateNodegroup", "eks:DescribeNodegroup", "eks:UpdateNodegroupConfig",
      "eks:UpdateNodegroupVersion", "eks:DeleteNodegroup", "eks:ListTagsForResource",
    ]
    resources = ["*"]
  }
  statement {
    sid = "LaunchTemplateLifecycle"
    actions = [
      "ec2:CreateLaunchTemplate", "ec2:CreateLaunchTemplateVersion",
      "ec2:DeleteLaunchTemplate", "ec2:DeleteLaunchTemplateVersions", "ec2:CreateTags",
      "ec2:DescribeAvailabilityZones", "ec2:DescribeInstances", "ec2:DescribeLaunchTemplates",
      "ec2:DescribeLaunchTemplateVersions", "ec2:DescribeRouteTables", "ec2:DescribeImages",
      "ec2:DescribeInstanceTypes", "ec2:DescribeInstanceTypeOfferings",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeSecurityGroups", "ec2:DescribeSubnets", "ec2:DescribeVpcs",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "RunRegionalInstancesForManagedNodes"
    actions   = ["ec2:RunInstances"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "ec2:Region"
      values   = [var.region]
    }
  }
  statement {
    sid       = "PassApprovedEksRoles"
    actions   = ["iam:PassRole"]
    resources = setunion(local.approved_cluster_role_arns, local.approved_node_role_arns)
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["eks.amazonaws.com", "ec2.amazonaws.com"]
    }
  }
  statement {
    sid       = "ReadApprovedEksRoles"
    actions   = ["iam:GetRole", "iam:ListAttachedRolePolicies"]
    resources = setunion(local.approved_cluster_role_arns, local.approved_node_role_arns)
  }
  statement {
    sid     = "ReadEksNodegroupServiceLinkedRole"
    actions = ["iam:GetRole"]
    resources = [
      "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/aws-service-role/eks-nodegroup.amazonaws.com/AWSServiceRoleForAmazonEKSNodegroup"
    ]
  }
  statement {
    sid       = "CreateEksServiceLinkedRoles"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "iam:AWSServiceName"
      values   = ["eks.amazonaws.com", "eks-nodegroup.amazonaws.com"]
    }
  }
  statement {
    sid       = "UseApprovedEncryptionKeys"
    actions   = ["kms:DescribeKey", "kms:GetKeyPolicy", "kms:CreateGrant", "kms:ListGrants", "kms:RevokeGrant"]
    resources = local.approved_kms_key_arns
  }
  statement {
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "provisioning" {
  name   = "NaviganEksProvisioning"
  role   = aws_iam_role.navigan.id
  policy = data.aws_iam_policy_document.provisioning.json
}

output "role_arn" { value = aws_iam_role.navigan.arn }
output "discovery_role_arn" {
  value = var.navigan_discovery_principal_arn == null ? null : aws_iam_role.discovery[0].arn
}
output "approved_cluster_role_arns" { value = local.approved_cluster_role_arns }
output "approved_node_role_arns" { value = local.approved_node_role_arns }
output "approved_kms_key_arns" { value = local.approved_kms_key_arns }
