mock_provider "aws" {
  override_during = plan

  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }

  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }

  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
}

variables {
  region                     = "ap-south-1"
  customer_id                = "CUS-storage-fixture"
  navigan_execution_role_arn = "arn:aws:iam::210987654321:role/NaviganTerraformExecution"
  external_id                = "test-only"
}

run "storage_permissions_are_opt_in" {
  command = plan

  assert {
    condition = (
      length(aws_iam_role.ebs_csi_controller) == 0 &&
      length(aws_iam_role_policy_attachment.ebs_csi_controller) == 0 &&
      length(aws_iam_role_policy.ebs_csi_provisioning) == 0 &&
      output.ebs_csi_controller_role_arn == null
    )
    error_message = "The default bootstrap must not create storage IAM."
  }
}

run "approved_clusters_get_scoped_storage_iam" {
  command = plan

  variables {
    ebs_csi_cluster_names    = ["active-eks", "new-eks"]
    permissions_boundary_arn = "arn:aws:iam::123456789012:policy/CustomerBoundary"
  }

  override_resource {
    target          = aws_iam_role.ebs_csi_controller[0]
    override_during = plan
    values          = { arn = "arn:aws:iam::123456789012:role/NaviganEbsCsiControllerRole" }
  }

  assert {
    condition = (
      output.ebs_csi_controller_role_arn == "arn:aws:iam::123456789012:role/NaviganEbsCsiControllerRole" &&
      aws_iam_role.ebs_csi_controller[0].permissions_boundary == var.permissions_boundary_arn &&
      aws_iam_role_policy_attachment.ebs_csi_controller[0].policy_arn == "arn:aws:iam::aws:policy/AmazonEBSCSIDriverEKSClusterScopedPolicy" &&
      jsondecode(aws_iam_role.ebs_csi_controller[0].assume_role_policy).Statement[0].Principal.Service == "pods.eks.amazonaws.com" &&
      jsondecode(aws_iam_role.ebs_csi_controller[0].assume_role_policy).Statement[0].Condition.StringEquals == {
        "aws:RequestTag/eks-cluster-arn"            = ["arn:aws:eks:ap-south-1:123456789012:cluster/active-eks", "arn:aws:eks:ap-south-1:123456789012:cluster/new-eks"]
        "aws:RequestTag/kubernetes-namespace"       = "kube-system"
        "aws:RequestTag/kubernetes-service-account" = "ebs-csi-controller-sa"
      }
    )
    error_message = "The controller must use the customer boundary and trust only the approved EKS Pod Identities."
  }

  assert {
    condition = (
      one([
        for item in jsondecode(aws_iam_role_policy.ebs_csi_provisioning[0].policy).Statement : item.Resource
        if item.Sid == "PassApprovedStorageControllerRole"
      ]) == output.ebs_csi_controller_role_arn &&
      one([
        for item in jsondecode(aws_iam_role_policy.ebs_csi_provisioning[0].policy).Statement : item.Condition.StringEquals["iam:PassedToService"]
        if item.Sid == "PassApprovedStorageControllerRole"
      ]) == "eks.amazonaws.com"
    )
    error_message = "The provisioner may pass only the dedicated controller role to EKS."
  }

  assert {
    condition = toset(one([
      for item in jsondecode(aws_iam_role_policy.ebs_csi_provisioning[0].policy).Statement : item.Resource
      if item.Sid == "CreateAddonOnApprovedClusters"
      ])) == toset([
      "arn:aws:eks:ap-south-1:123456789012:cluster/active-eks",
      "arn:aws:eks:ap-south-1:123456789012:cluster/new-eks",
      "arn:aws:eks:ap-south-1:123456789012:podidentityassociation/active-eks/*",
      "arn:aws:eks:ap-south-1:123456789012:podidentityassociation/new-eks/*",
    ])
    error_message = "Add-on creation must be scoped to exactly the approved clusters."
  }

  assert {
    condition = toset(one([
      for item in jsondecode(aws_iam_role_policy.ebs_csi_provisioning[0].policy).Statement : item.Resource
      if item.Sid == "MaintainStorageAddonsOnApprovedClusters"
      ])) == toset([
      "arn:aws:eks:ap-south-1:123456789012:addon/active-eks/aws-ebs-csi-driver/*",
      "arn:aws:eks:ap-south-1:123456789012:addon/active-eks/eks-pod-identity-agent/*",
      "arn:aws:eks:ap-south-1:123456789012:addon/new-eks/aws-ebs-csi-driver/*",
      "arn:aws:eks:ap-south-1:123456789012:addon/new-eks/eks-pod-identity-agent/*",
      "arn:aws:eks:ap-south-1:123456789012:podidentityassociation/active-eks/*",
      "arn:aws:eks:ap-south-1:123456789012:podidentityassociation/new-eks/*",
    ])
    error_message = "Storage add-on updates and deletions must be scoped to the two add-ons on approved clusters."
  }
}

run "reject_wildcard_cluster_scope" {
  command = plan

  variables {
    ebs_csi_cluster_names = ["active-*"]
  }

  expect_failures = [var.ebs_csi_cluster_names]
}
