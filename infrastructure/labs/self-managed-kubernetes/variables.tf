variable "aws_region" {
  description = "AWS region for the migration lab."
  type        = string
  default     = "ap-south-1"
}

variable "environment_name" {
  description = "Short environment identifier used in resource names."
  type        = string
  default     = "migration-lab"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.environment_name))
    error_message = "environment_name must be 3-31 lowercase letters, numbers, or hyphens."
  }
}

variable "vpc_cidr" {
  description = "CIDR assigned to the isolated lab VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "control_plane_instance_type" {
  description = "EC2 type for the single lab control-plane node."
  type        = string
  default     = "t3.large"
}

variable "worker_instance_type" {
  description = "EC2 type for worker nodes."
  type        = string
  default     = "t3.large"
}

variable "worker_count" {
  description = "Number of worker nodes. Two validates cross-node scheduling and communication."
  type        = number
  default     = 2

  validation {
    condition     = var.worker_count >= 2 && var.worker_count <= 5
    error_message = "worker_count must be between 2 and 5."
  }
}

variable "root_volume_size_gib" {
  description = "Encrypted gp3 root volume size for every node."
  type        = number
  default     = 40
}

variable "kubernetes_minor_version" {
  description = "Supported Kubernetes minor version installed from pkgs.k8s.io."
  type        = string
  default     = "1.37"

  validation {
    condition     = can(regex("^1\\.[0-9]{2}$", var.kubernetes_minor_version))
    error_message = "Use a Kubernetes minor version such as 1.37."
  }
}

variable "calico_version" {
  description = "Pinned Project Calico release."
  type        = string
  default     = "3.32.2"
}

variable "pod_cidr" {
  description = "Pod address range managed by Calico."
  type        = string
  default     = "192.168.0.0/16"
}

variable "service_cidr" {
  description = "Kubernetes service address range."
  type        = string
  default     = "10.96.0.0/12"
}

variable "enable_ssh" {
  description = "Enable SSH ingress from admin_cidr. SSM Session Manager remains the default."
  type        = bool
  default     = false
}

variable "admin_cidr" {
  description = "Trusted administrator CIDR used only when enable_ssh is true."
  type        = string
  default     = "127.0.0.1/32"

  validation {
    condition     = var.admin_cidr != "0.0.0.0/0"
    error_message = "Unrestricted administrative ingress is not allowed."
  }
}

variable "ssh_key_name" {
  description = "Optional existing EC2 key pair. Leave null when using SSM only."
  type        = string
  default     = null
}
