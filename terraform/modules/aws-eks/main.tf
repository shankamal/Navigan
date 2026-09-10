locals {
  node_groups = { for group in var.node_groups : group.name => group }
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

resource "aws_launch_template" "node" {
  for_each = local.node_groups

  name_prefix            = "${var.cluster_name}-${each.key}-"
  update_default_version = true

  network_interfaces {
    security_groups = var.node_security_group_ids
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
  for_each = local.node_groups

  cluster_name    = aws_eks_cluster.this.name
  node_group_name = each.key
  node_role_arn   = var.node_role_arn
  subnet_ids      = var.node_subnet_ids
  instance_types  = each.value.instanceTypes
  capacity_type   = each.value.capacityType

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

  tags = var.tags
}
