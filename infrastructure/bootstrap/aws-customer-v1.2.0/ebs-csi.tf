variable "ebs_csi_cluster_names" {
  description = "Approved EKS cluster names in this account and region that can use Navigan-managed EBS CSI."
  type        = set(string)
  default     = []
  nullable    = false

  validation {
    condition = alltrue([
      for name in var.ebs_csi_cluster_names : can(regex("^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$", name))
    ])
    error_message = "Supply exact EKS cluster names without wildcards."
  }
}

locals {
  ebs_csi_enabled = length(var.ebs_csi_cluster_names) > 0
  ebs_csi_eks_arn = "arn:${data.aws_partition.current.partition}:eks:${var.region}:${data.aws_caller_identity.current.account_id}"
  ebs_csi_cluster_arns = [
    for name in var.ebs_csi_cluster_names : "${local.ebs_csi_eks_arn}:cluster/${name}"
  ]
  ebs_csi_addon_arns = flatten([
    for name in var.ebs_csi_cluster_names : [
      "${local.ebs_csi_eks_arn}:addon/${name}/aws-ebs-csi-driver/*",
      "${local.ebs_csi_eks_arn}:addon/${name}/eks-pod-identity-agent/*",
    ]
  ])
  ebs_csi_association_arns = [
    for name in var.ebs_csi_cluster_names : "${local.ebs_csi_eks_arn}:podidentityassociation/${name}/*"
  ]
}

resource "aws_iam_role" "ebs_csi_controller" {
  count                = local.ebs_csi_enabled ? 1 : 0
  name                 = "NaviganEbsCsiControllerRole"
  permissions_boundary = var.permissions_boundary_arn
  tags                 = { ManagedBy = "Navigan", Purpose = "EbsCsiController", NaviganCustomerId = var.customer_id }
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
      Condition = {
        StringEquals = {
          "aws:RequestTag/eks-cluster-arn"            = local.ebs_csi_cluster_arns
          "aws:RequestTag/kubernetes-namespace"       = "kube-system"
          "aws:RequestTag/kubernetes-service-account" = "ebs-csi-controller-sa"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ebs_csi_controller" {
  count      = local.ebs_csi_enabled ? 1 : 0
  role       = aws_iam_role.ebs_csi_controller[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEBSCSIDriverEKSClusterScopedPolicy"
}

resource "aws_iam_role_policy" "ebs_csi_provisioning" {
  count = local.ebs_csi_enabled ? 1 : 0
  name  = "NaviganEksEbsCsiProvisioning"
  role  = aws_iam_role.navigan.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "ReadRegionalAddonConfiguration"
        Effect    = "Allow"
        Action    = "eks:DescribeAddonConfiguration"
        Resource  = "*"
        Condition = { StringEquals = { "aws:RequestedRegion" = var.region } }
      },
      {
        Sid      = "CreateAddonOnApprovedClusters"
        Effect   = "Allow"
        Action   = "eks:CreateAddon"
        Resource = concat(local.ebs_csi_cluster_arns, local.ebs_csi_association_arns)
      },
      {
        Sid      = "CreateStoragePodIdentityAssociationOnApprovedClusters"
        Effect   = "Allow"
        Action   = "eks:CreatePodIdentityAssociation"
        Resource = local.ebs_csi_cluster_arns
      },
      {
        Sid      = "MaintainStorageAddonsOnApprovedClusters"
        Effect   = "Allow"
        Action   = ["eks:UpdateAddon", "eks:DeleteAddon"]
        Resource = concat(local.ebs_csi_addon_arns, local.ebs_csi_association_arns)
      },
      {
        Sid      = "ReadAddonPodIdentityAssociations"
        Effect   = "Allow"
        Action   = "eks:DescribePodIdentityAssociation"
        Resource = local.ebs_csi_association_arns
      },
      {
        Sid      = "ReadApprovedStorageControllerRole"
        Effect   = "Allow"
        Action   = "iam:GetRole"
        Resource = aws_iam_role.ebs_csi_controller[0].arn
      },
      {
        Sid       = "PassApprovedStorageControllerRole"
        Effect    = "Allow"
        Action    = "iam:PassRole"
        Resource  = aws_iam_role.ebs_csi_controller[0].arn
        Condition = { StringEquals = { "iam:PassedToService" = ["eks.amazonaws.com", "pods.eks.amazonaws.com"] } }
      },
    ]
  })
}

output "ebs_csi_controller_role_arn" {
  description = "Controller ARN for the approved environment provisioning contract when EBS CSI is enabled."
  value       = one(aws_iam_role.ebs_csi_controller[*].arn)
}
