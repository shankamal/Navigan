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
