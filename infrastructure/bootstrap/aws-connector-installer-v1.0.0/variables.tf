variable "region" { type = string }
variable "customer_id" {
  type        = string
  description = "Immutable Navigan customer identifier used for tags and audit correlation."
}
variable "vpc_id" {
  type        = string
  description = "VPC containing the private EKS API endpoint."
}
variable "subnet_ids" {
  type        = set(string)
  description = "Private subnets used by the connector installer."
  validation {
    condition     = length(var.subnet_ids) >= 1
    error_message = "At least one private subnet is required."
  }
}
variable "security_group_ids" {
  type        = set(string)
  description = "Deprecated. The module now creates a stable dedicated installer security group."
  default     = []
}
variable "provisioning_role_name" {
  type        = string
  default     = "NaviganProvisioningRole"
  description = "Existing tenant-bound role assumed by the Navigan API."
}
variable "permissions_boundary_arn" {
  type     = string
  default  = null
  nullable = true
}
