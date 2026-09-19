data "aws_partition" "current" {}
data "aws_caller_identity" "current" {}
data "aws_iam_role" "provisioning" {
  name = var.provisioning_role_name
}

data "aws_iam_policy_document" "installer_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "installer" {
  name                 = "NaviganClusterInstallerRole"
  assume_role_policy   = data.aws_iam_policy_document.installer_trust.json
  permissions_boundary = var.permissions_boundary_arn
  tags = {
    ManagedBy         = "Navigan"
    Purpose           = "PrivateClusterConnectorInstallation"
    NaviganCustomerId = var.customer_id
  }
}

data "aws_iam_policy_document" "installer" {
  statement {
    sid       = "WriteBuildLogs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["*"]
  }
  statement {
    sid = "ManageVpcNetworkInterface"
    actions = [
      "ec2:CreateNetworkInterface",
      "ec2:CreateNetworkInterfacePermission",
      "ec2:DeleteNetworkInterface",
      "ec2:DescribeDhcpOptions",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSubnets",
      "ec2:DescribeVpcs",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "DescribeTargetEksCluster"
    actions   = ["eks:DescribeCluster"]
    resources = ["*"]
  }
  statement {
    sid     = "ReadEphemeralConnectorSecret"
    actions = ["secretsmanager:GetSecretValue", "secretsmanager:DeleteSecret"]
    resources = [
      "arn:${data.aws_partition.current.partition}:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:navigan/connectors/*"
    ]
  }
  statement {
    sid = "PullApprovedContainerImages"
    actions = [
      "ecr:GetAuthorizationToken",
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "installer" {
  name   = "NaviganPrivateClusterInstaller"
  role   = aws_iam_role.installer.id
  policy = data.aws_iam_policy_document.installer.json
}

resource "aws_codebuild_project" "installer" {
  name           = "NaviganClusterInstaller"
  description    = "API-triggered installation of the outbound-only Navigan connector"
  service_role   = aws_iam_role.installer.arn
  build_timeout  = 15
  queued_timeout = 15

  artifacts { type = "NO_ARTIFACTS" }
  source {
    type      = "NO_SOURCE"
    buildspec = file("${path.module}/buildspec.yml")
  }
  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/standard:7.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = false
  }
  vpc_config {
    vpc_id             = var.vpc_id
    subnets            = sort(tolist(var.subnet_ids))
    security_group_ids = sort(tolist(var.security_group_ids))
  }
  tags = {
    ManagedBy         = "Navigan"
    Purpose           = "PrivateClusterConnectorInstallation"
    NaviganCustomerId = var.customer_id
  }
}

data "aws_iam_policy_document" "control" {
  statement {
    sid       = "StartPrivateConnectorInstaller"
    actions   = ["codebuild:StartBuild", "codebuild:BatchGetBuilds"]
    resources = [aws_codebuild_project.installer.arn]
  }
  statement {
    sid       = "DenyConnectorBuildspecOverride"
    effect    = "Deny"
    actions   = ["codebuild:StartBuild"]
    resources = [aws_codebuild_project.installer.arn]
    condition {
      test     = "Null"
      variable = "codebuild:source.buildspec"
      values   = ["false"]
    }
  }
  statement {
    sid       = "DenyUnexpectedConnectorEnvironmentOverrides"
    effect    = "Deny"
    actions   = ["codebuild:StartBuild"]
    resources = [aws_codebuild_project.installer.arn]
    condition {
      test     = "ForAnyValue:StringNotEquals"
      variable = "codebuild:environment.environmentVariables.name"
      values   = ["NAVIGAN_CONNECTOR_INSTALLATION"]
    }
  }
  statement {
    sid = "ManageEphemeralConnectorSecrets"
    actions = [
      "secretsmanager:CreateSecret",
      "secretsmanager:DeleteSecret",
      "secretsmanager:TagResource",
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:navigan/connectors/*"
    ]
  }
  statement {
    sid = "ManageInstallerEksAccess"
    actions = [
      "eks:CreateAccessEntry",
      "eks:DescribeAccessEntry",
      "eks:DeleteAccessEntry",
      "eks:AssociateAccessPolicy",
      "eks:DisassociateAccessPolicy",
      "eks:ListAssociatedAccessPolicies",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "control" {
  name   = "NaviganConnectorInstallerControl"
  role   = data.aws_iam_role.provisioning.id
  policy = data.aws_iam_policy_document.control.json
}

output "connector_installer_project_name" {
  value = aws_codebuild_project.installer.name
}
output "connector_installer_role_arn" {
  value = aws_iam_role.installer.arn
}
