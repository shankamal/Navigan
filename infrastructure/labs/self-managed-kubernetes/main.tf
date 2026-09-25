data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_ssm_parameter" "ubuntu_ami" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

locals {
  name                = "navigan-${var.environment_name}"
  subnet_count        = 2
  join_parameter_name = "/navigan/${var.environment_name}/kubernetes/join-command"
  cluster_ready_name  = "/navigan/${var.environment_name}/kubernetes/ready"
  workload_object_key = "bootstrap/reference-application.zip"

  common_bootstrap = templatefile("${path.module}/templates/common.sh.tftpl", {
    kubernetes_minor_version = var.kubernetes_minor_version
  })
}

resource "random_id" "artifact_bucket" {
  byte_length = 4
}

data "archive_file" "reference_application" {
  type        = "zip"
  source_dir  = "${path.module}/workloads/reference-application"
  output_path = "${path.root}/.terraform/reference-application.zip"
}

resource "aws_s3_bucket" "artifacts" {
  bucket        = "${local.name}-artifacts-${random_id.artifact_bucket.hex}"
  force_destroy = true

  tags = { Name = "${local.name}-artifacts" }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_object" "reference_application" {
  bucket      = aws_s3_bucket.artifacts.id
  key         = local.workload_object_key
  source      = data.archive_file.reference_application.output_path
  source_hash = data.archive_file.reference_application.output_base64sha256

  server_side_encryption = "AES256"

  depends_on = [
    aws_s3_bucket_public_access_block.artifacts,
    aws_s3_bucket_server_side_encryption_configuration.artifacts,
  ]
}

resource "aws_vpc" "lab" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${local.name}-vpc" }
}

resource "aws_internet_gateway" "lab" {
  vpc_id = aws_vpc.lab.id
  tags   = { Name = "${local.name}-igw" }
}

resource "aws_subnet" "public" {
  count = local.subnet_count

  vpc_id                  = aws_vpc.lab.id
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index + 1)
  map_public_ip_on_launch = true

  tags = {
    Name                     = "${local.name}-public-${count.index + 1}"
    "kubernetes.io/role/elb" = "1"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.lab.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.lab.id
  }

  tags = { Name = "${local.name}-public" }
}

resource "aws_route_table_association" "public" {
  count = local.subnet_count

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "nodes" {
  name_prefix = "${local.name}-nodes-"
  description = "Kubernetes node communication for the Navigan migration lab"
  vpc_id      = aws_vpc.lab.id

  ingress {
    description = "All communication between Kubernetes nodes"
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    self        = true
  }

  dynamic "ingress" {
    for_each = var.enable_ssh ? [1] : []
    content {
      description = "Optional administrator SSH"
      protocol    = "tcp"
      from_port   = 22
      to_port     = 22
      cidr_blocks = [var.admin_cidr]
    }
  }

  egress {
    description = "Package repositories, AWS APIs, container registries, and external test services"
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = { Name = "${local.name}-nodes" }
}

resource "aws_iam_role" "nodes" {
  name_prefix        = "${local.name}-nodes-"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.nodes.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.nodes.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

data "aws_iam_policy_document" "bootstrap" {
  statement {
    sid = "ExchangeKubeadmJoinState"
    actions = [
      "ssm:GetParameter",
      "ssm:PutParameter",
      "ssm:DeleteParameter",
    ]
    resources = [
      "arn:aws:ssm:${var.aws_region}:*:parameter${local.join_parameter_name}",
      "arn:aws:ssm:${var.aws_region}:*:parameter${local.cluster_ready_name}",
    ]
  }

  statement {
    sid       = "ReadBootstrapArtifact"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.artifacts.arn}/${local.workload_object_key}"]
  }
}

resource "aws_iam_role_policy" "bootstrap" {
  name   = "kubeadm-bootstrap"
  role   = aws_iam_role.nodes.id
  policy = data.aws_iam_policy_document.bootstrap.json
}

resource "aws_iam_instance_profile" "nodes" {
  name_prefix = "${local.name}-nodes-"
  role        = aws_iam_role.nodes.name
}

resource "aws_instance" "control_plane" {
  ami                         = data.aws_ssm_parameter.ubuntu_ami.value
  instance_type               = var.control_plane_instance_type
  subnet_id                   = aws_subnet.public[0].id
  vpc_security_group_ids      = [aws_security_group.nodes.id]
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.nodes.name
  key_name                    = var.ssh_key_name

  user_data_replace_on_change = true
  user_data = templatefile("${path.module}/templates/control-plane.sh.tftpl", {
    common_bootstrap    = local.common_bootstrap
    aws_region          = var.aws_region
    join_parameter_name = local.join_parameter_name
    cluster_ready_name  = local.cluster_ready_name
    kubernetes_version  = var.kubernetes_minor_version
    pod_cidr            = var.pod_cidr
    service_cidr        = var.service_cidr
    calico_version      = var.calico_version
    worker_count        = var.worker_count
    workload_bucket     = aws_s3_bucket.artifacts.id
    workload_object_key = local.workload_object_key
  })

  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = var.root_volume_size_gib
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  tags = {
    Name                              = "${local.name}-control-plane"
    "navigan.io/kubernetes-node-role" = "control-plane"
  }

  depends_on = [
    aws_iam_role_policy.bootstrap,
    aws_iam_role_policy_attachment.ebs_csi,
    aws_iam_role_policy_attachment.ssm,
    aws_route_table_association.public,
    aws_s3_object.reference_application,
  ]
}

resource "aws_instance" "worker" {
  count = var.worker_count

  ami                         = data.aws_ssm_parameter.ubuntu_ami.value
  instance_type               = var.worker_instance_type
  subnet_id                   = aws_subnet.public[count.index % local.subnet_count].id
  vpc_security_group_ids      = [aws_security_group.nodes.id]
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.nodes.name
  key_name                    = var.ssh_key_name

  user_data_replace_on_change = true
  user_data = templatefile("${path.module}/templates/worker.sh.tftpl", {
    common_bootstrap    = local.common_bootstrap
    aws_region          = var.aws_region
    join_parameter_name = local.join_parameter_name
    worker_index        = count.index + 1
  })

  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = var.root_volume_size_gib
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  tags = {
    Name                              = "${local.name}-worker-${count.index + 1}"
    "navigan.io/kubernetes-node-role" = "worker"
  }

  depends_on = [
    aws_instance.control_plane,
    aws_iam_role_policy.bootstrap,
    aws_iam_role_policy_attachment.ebs_csi,
    aws_iam_role_policy_attachment.ssm,
    aws_route_table_association.public,
  ]
}
