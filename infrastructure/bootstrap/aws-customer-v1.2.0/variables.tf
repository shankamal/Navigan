variable "region" { type = string }
variable "customer_id" {
  description = "Immutable Navigan customer identifier used to bind and audit STS sessions."
  type        = string
}
variable "navigan_execution_role_arn" { type = string }
variable "navigan_validation_role_arn" {
  description = "ARN of the Navigan Environment Lambda role that performs read-only blueprint readiness validation."
  type        = string
  default     = null
}
variable "navigan_connector_principal_arns" {
  description = "Exact Navigan Cluster and Status Lambda role ARNs allowed to orchestrate secure connector bootstrap."
  type        = set(string)
  default     = []
}
variable "navigan_discovery_principal_arn" {
  description = "ARN of the Navigan environment-discovery Lambda execution role. When supplied, the bootstrap creates NaviganDiscoveryRole."
  type        = string
  default     = null
}
variable "external_id" {
  type      = string
  sensitive = true
}
variable "eks_cluster_role_arns" {
  description = "Existing customer EKS cluster roles approved for Navigan."
  type        = set(string)
  default     = []
}
variable "eks_node_role_arns" {
  description = "Existing customer EKS node roles approved for Navigan."
  type        = set(string)
  default     = []
}
variable "kms_key_arns" {
  description = "Existing customer-managed KMS keys approved for EKS node volumes."
  type        = set(string)
  default     = []
}
variable "create_recommended_eks_resources" {
  description = "Create least-privilege EKS cluster/node roles and a symmetric KMS key when the customer has no eligible resources."
  type        = bool
  default     = false
}
variable "create_eks_cluster_role" {
  description = "Create a dedicated EKS cluster role using eks_cluster_role_name."
  type        = bool
  default     = false
}
variable "eks_cluster_role_name" {
  type    = string
  default = "NaviganEksClusterRole"
  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,64}$", var.eks_cluster_role_name))
    error_message = "Use a valid IAM role name."
  }
}
variable "create_eks_node_role" {
  description = "Create a dedicated EKS node role using eks_node_role_name."
  type        = bool
  default     = false
}
variable "eks_node_role_name" {
  type    = string
  default = "NaviganEksNodeRole"
  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,64}$", var.eks_node_role_name))
    error_message = "Use a valid IAM role name."
  }
}
variable "create_eks_kms_key" {
  description = "Create a dedicated symmetric KMS key using recommended_kms_alias."
  type        = bool
  default     = false
}
variable "confirm_create_recommended_resources" {
  description = "Explicit confirmation that the reviewed IAM roles and KMS key may be created. Required when create_recommended_eks_resources is true."
  type        = bool
  default     = false
}
variable "recommended_kms_alias" {
  type    = string
  default = "alias/navigan-eks"
}
variable "permissions_boundary_arn" {
  type    = string
  default = null
}
variable "create_connector_installer" {
  description = "Create the customer-side CodeBuild installer used for private EKS connector deployment."
  type        = bool
  default     = false
}
variable "connector_installer_vpc_id" {
  description = "Customer VPC containing the private EKS API endpoints."
  type        = string
  default     = null
  nullable    = true
}
variable "connector_installer_subnet_ids" {
  description = "Private customer subnets used by the connector installer."
  type        = set(string)
  default     = []
}
variable "connector_installer_security_group_ids" {
  description = "Deprecated. A stable dedicated installer security group is created automatically."
  type        = set(string)
  default     = []
}
