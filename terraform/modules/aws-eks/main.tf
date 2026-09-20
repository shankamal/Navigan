locals {
  node_groups = { for group in var.node_groups : group.name => group }
  managed_node_groups = {
    for name, group in local.node_groups : name => group
    if group.managementMode == "MANAGED"
  }
  adopted_node_groups = {
    for name, group in local.node_groups : name => group
    if group.managementMode == "ADOPTED"
  }
}

resource "aws_security_group" "managed_nodes" {
  name_prefix = "${var.cluster_name}-navigan-nodes-"
  description = "Navigan-managed shared security group for all EKS worker nodes"
  vpc_id      = var.vpc_id

  tags = merge(var.tags, {
    Name               = "${var.cluster_name}-navigan-nodes"
    NaviganManagedRole = "SHARED_NODE_NETWORK"
  })
}

resource "aws_vpc_security_group_ingress_rule" "managed_nodes_self" {
  security_group_id            = aws_security_group.managed_nodes.id
  referenced_security_group_id = aws_security_group.managed_nodes.id
  ip_protocol                  = "-1"
  description                  = "Allow communication between all Navigan-managed cluster nodes"
}

resource "aws_vpc_security_group_egress_rule" "managed_nodes_ipv4" {
  security_group_id = aws_security_group.managed_nodes.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Allow worker node egress"
}

resource "aws_eks_cluster" "this" {
  name     = var.cluster_name
  role_arn = var.cluster_role_arn
  version  = var.kubernetes_version

  vpc_config {
    subnet_ids              = var.cluster_subnet_ids
    security_group_ids      = var.cluster_security_group_ids
    endpoint_private_access = true
    endpoint_public_access  = var.endpoint_access == "PUBLIC_AND_PRIVATE"
  }

  dynamic "encryption_config" {
    for_each = var.cluster_secrets_kms_key_arn == null ? [] : [var.cluster_secrets_kms_key_arn]
    content {
      provider {
        key_arn = encryption_config.value
      }
      resources = ["secrets"]
    }
  }

  access_config {
    authentication_mode = "API_AND_CONFIG_MAP"
  }

  tags = var.tags
}

resource "aws_vpc_security_group_ingress_rule" "managed_nodes_from_control_plane_https" {
  security_group_id            = aws_security_group.managed_nodes.id
  referenced_security_group_id = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
  description                  = "Allow EKS control plane HTTPS traffic to worker nodes"
}

resource "aws_vpc_security_group_ingress_rule" "managed_nodes_from_control_plane_kubelet" {
  security_group_id            = aws_security_group.managed_nodes.id
  referenced_security_group_id = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  from_port                    = 1025
  to_port                      = 65535
  ip_protocol                  = "tcp"
  description                  = "Allow EKS control plane kubelet and webhook traffic to worker nodes"
}

resource "aws_vpc_security_group_ingress_rule" "control_plane_from_managed_nodes_https" {
  security_group_id            = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  referenced_security_group_id = aws_security_group.managed_nodes.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
  description                  = "Allow worker nodes to reach the EKS control plane"
}

resource "aws_vpc_security_group_ingress_rule" "control_plane_from_installer_https" {
  count                        = var.installer_security_group_id == null ? 0 : 1
  security_group_id            = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  referenced_security_group_id = var.installer_security_group_id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
  description                  = "Allow the stable Navigan installer to reach the EKS API"
}

resource "aws_launch_template" "node" {
  for_each = local.managed_node_groups

  name_prefix            = "${var.cluster_name}-${each.key}-"
  update_default_version = true

  network_interfaces {
    security_groups = distinct(concat(
      var.node_security_group_ids,
      [aws_security_group.managed_nodes.id],
    ))
  }

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      encrypted   = true
      kms_key_id  = var.node_volume_kms_key_arn
      volume_size = each.value.diskSizeGiB
      volume_type = "gp3"
    }
  }

  tag_specifications {
    resource_type = "instance"
    tags          = merge(var.tags, { Name = "${var.cluster_name}-${each.key}" })
  }

  tags = var.tags
}

resource "aws_eks_node_group" "this" {
  for_each = local.managed_node_groups

  cluster_name    = aws_eks_cluster.this.name
  node_group_name = each.key
  node_role_arn   = var.node_role_arn
  subnet_ids      = var.node_subnet_ids
  instance_types  = each.value.instanceTypes
  capacity_type   = each.value.capacityType
  labels = merge(
    {
      "navigan.io/node-purpose" = lower(each.value.purpose)
      "navigan.io/managed-by"   = "navigan"
    },
    each.value.purpose == "SYSTEM" ? {
      "navigan.io/platform-services" = "true"
    } : {}
  )

  scaling_config {
    desired_size = each.value.desiredSize
    min_size     = each.value.minSize
    max_size     = each.value.maxSize
  }

  launch_template {
    id      = aws_launch_template.node[each.key].id
    version = aws_launch_template.node[each.key].latest_version
  }

  update_config {
    max_unavailable_percentage = 25
  }

  dynamic "taint" {
    for_each = each.value.purpose == "SYSTEM" ? [1] : []
    content {
      key    = "navigan.io/system-only"
      value  = "true"
      effect = "NO_SCHEDULE"
    }
  }

  tags = merge(var.tags, {
    "NaviganNodePurpose" = each.value.purpose
  })

  depends_on = [
    aws_vpc_security_group_ingress_rule.managed_nodes_self,
    aws_vpc_security_group_ingress_rule.managed_nodes_from_control_plane_https,
    aws_vpc_security_group_ingress_rule.managed_nodes_from_control_plane_kubelet,
    aws_vpc_security_group_ingress_rule.control_plane_from_managed_nodes_https,
    aws_vpc_security_group_egress_rule.managed_nodes_ipv4,
  ]
}

data "aws_eks_node_group" "adopted" {
  for_each = local.adopted_node_groups

  cluster_name    = aws_eks_cluster.this.name
  node_group_name = each.key
}
