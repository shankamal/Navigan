data "aws_iam_policy_document" "trust" {
  statement {
    sid     = "NaviganTenantBoundProvisioningAndValidation"
    actions = ["sts:AssumeRole"]
    principals {
      type = "AWS"
      identifiers = concat(
        compact([
          var.navigan_execution_role_arn,
          var.navigan_validation_role_arn,
        ]),
        sort(tolist(var.navigan_connector_principal_arns))
      )
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

locals {
  create_cluster_role = var.create_recommended_eks_resources || var.create_eks_cluster_role
  create_node_role    = var.create_recommended_eks_resources || var.create_eks_node_role
  create_kms_key      = var.create_recommended_eks_resources || var.create_eks_kms_key
}

resource "aws_iam_role" "eks_cluster" {
  count                = local.create_cluster_role ? 1 : 0
  name                 = var.eks_cluster_role_name
  assume_role_policy   = data.aws_iam_policy_document.eks_cluster_trust.json
  permissions_boundary = var.permissions_boundary_arn
  tags                 = { ManagedBy = "Navigan", Purpose = "EKSCluster", NaviganCustomerId = var.customer_id }
}

resource "aws_iam_role_policy_attachment" "eks_cluster" {
  count      = local.create_cluster_role ? 1 : 0
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
  count                = local.create_node_role ? 1 : 0
  name                 = var.eks_node_role_name
  assume_role_policy   = data.aws_iam_policy_document.eks_node_trust.json
  permissions_boundary = var.permissions_boundary_arn
  tags                 = { ManagedBy = "Navigan", Purpose = "EKSNode", NaviganCustomerId = var.customer_id }
}

resource "aws_iam_role_policy_attachment" "eks_node" {
  for_each = local.create_node_role ? toset([
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
  count                   = local.create_kms_key ? 1 : 0
  description             = "Navigan EKS node-volume encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.eks_kms.json
  tags                    = { ManagedBy = "Navigan", Purpose = "EKSNodeEncryption", NaviganCustomerId = var.customer_id }
}

resource "aws_kms_alias" "eks" {
  count         = local.create_kms_key ? 1 : 0
  name          = var.recommended_kms_alias
  target_key_id = aws_kms_key.eks[0].key_id
}

check "automatic_resource_creation_confirmed" {
  assert {
    condition = (
      !(local.create_cluster_role || local.create_node_role || local.create_kms_key) ||
      var.confirm_create_recommended_resources
    )
    error_message = "Automatic EKS IAM/KMS creation requires confirm_create_recommended_resources = true after reviewing the plan."
  }
}

locals {
  approved_cluster_role_arns = setunion(
    var.eks_cluster_role_arns,
    local.create_cluster_role ? toset([aws_iam_role.eks_cluster[0].arn]) : toset([])
  )
  approved_node_role_arns = setunion(
    var.eks_node_role_arns,
    local.create_node_role ? toset([aws_iam_role.eks_node[0].arn]) : toset([])
  )
  approved_kms_key_arns = setunion(
    var.kms_key_arns,
    local.create_kms_key ? toset([aws_kms_key.eks[0].arn]) : toset([])
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
      "eks:CreateAccessEntry", "eks:DescribeAccessEntry", "eks:DeleteAccessEntry",
      "eks:AssociateAccessPolicy", "eks:DisassociateAccessPolicy",
      "eks:ListAssociatedAccessPolicies",
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
      "ec2:DescribeSecurityGroups", "ec2:DescribeSecurityGroupRules",
      "ec2:DescribeSubnets", "ec2:DescribeVpcs",
      "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup",
      "ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress", "ec2:RevokeSecurityGroupEgress",
      "ec2:ModifySecurityGroupRules", "ec2:DeleteTags",
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
  dynamic "statement" {
    for_each = var.create_connector_installer ? [1] : []
    content {
      sid = "StartPrivateConnectorInstaller"
      actions = [
        "codebuild:StartBuild",
        "codebuild:BatchGetBuilds",
      ]
      resources = [aws_codebuild_project.connector_installer[0].arn]
    }
  }
  dynamic "statement" {
    for_each = var.create_connector_installer ? [1] : []
    content {
      sid       = "DenyConnectorBuildspecOverride"
      effect    = "Deny"
      actions   = ["codebuild:StartBuild"]
      resources = [aws_codebuild_project.connector_installer[0].arn]
      condition {
        test     = "Null"
        variable = "codebuild:source.buildspec"
        values   = ["false"]
      }
    }
  }
  dynamic "statement" {
    for_each = var.create_connector_installer ? [1] : []
    content {
      sid       = "DenyUnexpectedConnectorEnvironmentOverrides"
      effect    = "Deny"
      actions   = ["codebuild:StartBuild"]
      resources = [aws_codebuild_project.connector_installer[0].arn]
      condition {
        test     = "ForAnyValue:StringNotEquals"
        variable = "codebuild:environment.environmentVariables.name"
        values   = ["NAVIGAN_CONNECTOR_INSTALLATION"]
      }
    }
  }
  dynamic "statement" {
    for_each = var.create_connector_installer ? [1] : []
    content {
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
  }
}

resource "aws_iam_role_policy" "provisioning" {
  name   = "NaviganEksProvisioning"
  role   = aws_iam_role.navigan.id
  policy = data.aws_iam_policy_document.provisioning.json
}

check "connector_installer_network_is_complete" {
  assert {
    condition = (
      !var.create_connector_installer ||
      (
        var.connector_installer_vpc_id != null &&
        length(var.connector_installer_subnet_ids) >= 1 &&
        length(var.connector_installer_security_group_ids) >= 1
      )
    )
    error_message = "Connector installer creation requires a VPC, private subnet, and security group."
  }
}

data "aws_iam_policy_document" "connector_installer_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "connector_installer" {
  count                = var.create_connector_installer ? 1 : 0
  name                 = "NaviganClusterInstallerRole"
  assume_role_policy   = data.aws_iam_policy_document.connector_installer_trust.json
  permissions_boundary = var.permissions_boundary_arn
  tags = {
    ManagedBy         = "Navigan"
    Purpose           = "PrivateClusterConnectorInstallation"
    NaviganCustomerId = var.customer_id
  }
}

data "aws_iam_policy_document" "connector_installer" {
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

resource "aws_iam_role_policy" "connector_installer" {
  count  = var.create_connector_installer ? 1 : 0
  name   = "NaviganPrivateClusterInstaller"
  role   = aws_iam_role.connector_installer[0].id
  policy = data.aws_iam_policy_document.connector_installer.json
}

resource "aws_codebuild_project" "connector_installer" {
  count          = var.create_connector_installer ? 1 : 0
  name           = "NaviganClusterInstaller"
  description    = "API-triggered installation of the outbound-only Navigan connector"
  service_role   = aws_iam_role.connector_installer[0].arn
  build_timeout  = 15
  queued_timeout = 15

  artifacts { type = "NO_ARTIFACTS" }
  source {
    type      = "NO_SOURCE"
    buildspec = <<-EOT
      version: 0.2
      phases:
        build:
          commands:
            - set -eu
            - PAYLOAD="$NAVIGAN_CONNECTOR_INSTALLATION"
            - CLUSTER_NAME="$(printf '%s' "$PAYLOAD" | jq -r '.clusterName')"
            - CONNECTOR_ID="$(printf '%s' "$PAYLOAD" | jq -r '.connectorId')"
            - SECRET_ARN="$(printf '%s' "$PAYLOAD" | jq -r '.connectorSecretArn')"
            - CONNECTOR_IMAGE="$(printf '%s' "$PAYLOAD" | jq -r '.connectorImage')"
            - API_BASE_URL="$(printf '%s' "$PAYLOAD" | jq -r '.apiBaseUrl')"
            - test "$(printf '%s' "$PAYLOAD" | jq -r '.schemaVersion')" = "1.0"
            - printf '%s' "$CLUSTER_NAME" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$'
            - printf '%s' "$CONNECTOR_ID" | grep -Eq '^KCC-[a-f0-9]{32}$'
            - printf '%s' "$CONNECTOR_IMAGE" | grep -Eq '^[A-Za-z0-9./:@_-]+$'
            - printf '%s' "$API_BASE_URL" | grep -Eq '^https://[A-Za-z0-9.-]+(/[A-Za-z0-9/_-]+)?$'
            - KUBERNETES_VERSION="$(aws eks describe-cluster --name "$CLUSTER_NAME" --query 'cluster.version' --output text)"
            - curl --fail --silent --show-error --location --http1.1 --retry 5 --retry-all-errors --retry-delay 2 --output /tmp/kubectl "https://dl.k8s.io/release/v$${KUBERNETES_VERSION}.0/bin/linux/amd64/kubectl"
            - curl --fail --silent --show-error --location --http1.1 --retry 5 --retry-all-errors --retry-delay 2 --output /tmp/kubectl.sha256 "https://dl.k8s.io/release/v$${KUBERNETES_VERSION}.0/bin/linux/amd64/kubectl.sha256"
            - echo "$(cat /tmp/kubectl.sha256)  /tmp/kubectl" | sha256sum --check
            - chmod 0700 /tmp/kubectl
            - aws eks update-kubeconfig --name "$CLUSTER_NAME" --kubeconfig /tmp/navigan-kubeconfig
            - |
              ELIGIBLE_NODES=$$(
                /tmp/kubectl --kubeconfig /tmp/navigan-kubeconfig get nodes -o json |
                jq -r '
                  .items[]
                  | select(.spec.unschedulable != true)
                  | select(any(.status.conditions[]; .type == "Ready" and .status == "True"))
                  | select(
                      [.spec.taints[]?
                        | select(
                            (.effect == "NoSchedule" or .effect == "NoExecute")
                            and .key != "navigan.io/system-only"
                          )
                      ] | length == 0
                    )
                  | .metadata.name
                '
              )
              if [ -z "$$ELIGIBLE_NODES" ]; then
                echo "No Ready node tolerates the Navigan system connector."
                /tmp/kubectl --kubeconfig /tmp/navigan-kubeconfig get nodes \
                  -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,UNSCHEDULABLE:.spec.unschedulable,TAINTS:.spec.taints'
                exit 1
              fi
              HAS_FREE_SLOT=false
              for NODE in $$ELIGIBLE_NODES; do
                ALLOCATABLE=$$(
                  /tmp/kubectl --kubeconfig /tmp/navigan-kubeconfig get node "$$NODE" \
                    -o jsonpath='{.status.allocatable.pods}'
                )
                USED=$$(
                  /tmp/kubectl --kubeconfig /tmp/navigan-kubeconfig get pods --all-namespaces \
                    --field-selector "spec.nodeName=$$NODE" --no-headers 2>/dev/null |
                  wc -l
                )
                echo "Connector scheduling preflight: node=$$NODE pods=$$USED/$$ALLOCATABLE"
                if [ "$$USED" -lt "$$ALLOCATABLE" ]; then
                  HAS_FREE_SLOT=true
                fi
              done
              AVAILABLE_REPLICAS=$$(
                /tmp/kubectl --kubeconfig /tmp/navigan-kubeconfig -n navigan-system \
                  get deployment navigan-cluster-connector \
                  -o jsonpath='{.status.availableReplicas}' 2>/dev/null || true
              )
              AVAILABLE_REPLICAS=$${AVAILABLE_REPLICAS:-0}
              if [ "$$HAS_FREE_SLOT" != "true" ] && [ "$$AVAILABLE_REPLICAS" -lt 1 ]; then
                echo "No schedulable pod slot is available and no healthy connector can release a slot."
                /tmp/kubectl --kubeconfig /tmp/navigan-kubeconfig get nodes \
                  -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,UNSCHEDULABLE:.spec.unschedulable,TAINTS:.spec.taints,MAX_PODS:.status.allocatable.pods'
                exit 1
              fi
            - install -m 0600 /dev/null /tmp/connector-token
            - aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" --query SecretString --output text > /tmp/connector-token
            - /tmp/kubectl --kubeconfig /tmp/navigan-kubeconfig create namespace navigan-system --dry-run=client -o yaml | /tmp/kubectl --kubeconfig /tmp/navigan-kubeconfig apply -f -
            - /tmp/kubectl --kubeconfig /tmp/navigan-kubeconfig -n navigan-system create secret generic navigan-cluster-connector --from-file=token=/tmp/connector-token --dry-run=client -o yaml | /tmp/kubectl --kubeconfig /tmp/navigan-kubeconfig apply -f -
            - |
              /tmp/kubectl --kubeconfig /tmp/navigan-kubeconfig apply -f - <<YAML
              apiVersion: v1
              kind: ServiceAccount
              metadata:
                name: navigan-cluster-connector
                namespace: navigan-system
              ---
              apiVersion: rbac.authorization.k8s.io/v1
              kind: ClusterRole
              metadata:
                name: navigan-cluster-connector
              rules:
                - apiGroups: [""]
                  resources: ["namespaces"]
                  verbs: ["get", "list", "watch"]
                - apiGroups: ["rbac.authorization.k8s.io"]
                  resources: ["roles", "rolebindings", "clusterroles", "clusterrolebindings"]
                  verbs: ["get", "list", "create", "update", "patch", "delete"]
                - apiGroups: [""]
                  resources: ["nodes", "namespaces", "pods", "pods/log", "services", "configmaps", "events"]
                  verbs: ["get", "list", "watch"]
                - apiGroups: ["apps"]
                  resources: ["deployments", "statefulsets", "daemonsets", "replicasets"]
                  verbs: ["get", "list", "watch", "patch", "update"]
                - apiGroups: ["argoproj.io"]
                  resources: ["applications"]
                  verbs: ["get", "list", "watch"]
              ---
              apiVersion: rbac.authorization.k8s.io/v1
              kind: ClusterRoleBinding
              metadata:
                name: navigan-cluster-connector
              roleRef:
                apiGroup: rbac.authorization.k8s.io
                kind: ClusterRole
                name: navigan-cluster-connector
              subjects:
                - kind: ServiceAccount
                  name: navigan-cluster-connector
                  namespace: navigan-system
              ---
              apiVersion: apps/v1
              kind: Deployment
              metadata:
                name: navigan-cluster-connector
                namespace: navigan-system
              spec:
                replicas: 1
                strategy:
                  type: Recreate
                selector:
                  matchLabels:
                    app.kubernetes.io/name: navigan-cluster-connector
                template:
                  metadata:
                    labels:
                      app.kubernetes.io/name: navigan-cluster-connector
                  spec:
                    serviceAccountName: navigan-cluster-connector
                    automountServiceAccountToken: true
                    tolerations:
                      - key: navigan.io/system-only
                        operator: Equal
                        value: "true"
                        effect: NoSchedule
                    securityContext:
                      runAsNonRoot: true
                      seccompProfile:
                        type: RuntimeDefault
                    containers:
                      - name: connector
                        image: "$CONNECTOR_IMAGE"
                        imagePullPolicy: IfNotPresent
                        securityContext:
                          allowPrivilegeEscalation: false
                          readOnlyRootFilesystem: true
                          capabilities:
                            drop: ["ALL"]
                        env:
                          - name: NAVIGAN_API_BASE_URL
                            value: "$API_BASE_URL"
                          - name: NAVIGAN_CONNECTOR_ID
                            value: "$CONNECTOR_ID"
                          - name: NAVIGAN_CONNECTOR_TOKEN
                            valueFrom:
                              secretKeyRef:
                                name: navigan-cluster-connector
                                key: token
                          - name: SYNC_INTERVAL_SECONDS
                            value: "60"
                        resources:
                          requests:
                            cpu: 10m
                            memory: 32Mi
                          limits:
                            cpu: 100m
                            memory: 64Mi
              YAML
            - |
              if ! /tmp/kubectl --kubeconfig /tmp/navigan-kubeconfig -n navigan-system rollout status deployment/navigan-cluster-connector --timeout=5m; then
                /tmp/kubectl --kubeconfig /tmp/navigan-kubeconfig -n navigan-system get pods -o wide || true
                /tmp/kubectl --kubeconfig /tmp/navigan-kubeconfig -n navigan-system describe pods -l app.kubernetes.io/name=navigan-cluster-connector || true
                /tmp/kubectl --kubeconfig /tmp/navigan-kubeconfig -n navigan-system get events --sort-by=.lastTimestamp || true
                exit 1
              fi
            - aws secretsmanager delete-secret --secret-id "$SECRET_ARN" --force-delete-without-recovery
          finally:
            - rm -f /tmp/connector-token /tmp/navigan-kubeconfig /tmp/kubectl /tmp/kubectl.sha256
    EOT
  }
  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/standard:7.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = false
  }
  vpc_config {
    vpc_id             = var.connector_installer_vpc_id
    subnets            = sort(tolist(var.connector_installer_subnet_ids))
    security_group_ids = sort(tolist(var.connector_installer_security_group_ids))
  }
  tags = {
    ManagedBy         = "Navigan"
    Purpose           = "PrivateClusterConnectorInstallation"
    NaviganCustomerId = var.customer_id
  }
}

output "role_arn" { value = aws_iam_role.navigan.arn }
output "discovery_role_arn" {
  value = var.navigan_discovery_principal_arn == null ? null : aws_iam_role.discovery[0].arn
}
output "approved_cluster_role_arns" { value = local.approved_cluster_role_arns }
output "approved_node_role_arns" { value = local.approved_node_role_arns }
output "approved_kms_key_arns" { value = local.approved_kms_key_arns }
output "connector_installer_project_name" {
  value = var.create_connector_installer ? aws_codebuild_project.connector_installer[0].name : null
}
output "connector_installer_role_arn" {
  value = var.create_connector_installer ? aws_iam_role.connector_installer[0].arn : null
}
