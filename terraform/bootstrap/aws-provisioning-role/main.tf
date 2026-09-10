data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [var.navigan_execution_role_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [var.external_id]
    }
  }
}

resource "aws_iam_role" "navigan" {
  name                 = "NaviganProvisioningRole"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  permissions_boundary = var.permissions_boundary_arn
  tags                 = { ManagedBy = "Navigan", Purpose = "EKSProvisioning" }
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
      "ec2:DescribeInstanceTypes", "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeSecurityGroups", "ec2:DescribeSubnets", "ec2:DescribeVpcs",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "PassApprovedEksRoles"
    actions   = ["iam:PassRole"]
    resources = setunion(var.eks_cluster_role_arns, var.eks_node_role_arns)
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["eks.amazonaws.com", "ec2.amazonaws.com"]
    }
  }
  statement {
    sid       = "ReadApprovedEksRoles"
    actions   = ["iam:GetRole"]
    resources = setunion(var.eks_cluster_role_arns, var.eks_node_role_arns)
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
    actions   = ["kms:DescribeKey", "kms:CreateGrant", "kms:ListGrants", "kms:RevokeGrant"]
    resources = var.kms_key_arns
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
