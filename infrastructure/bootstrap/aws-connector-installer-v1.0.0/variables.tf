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
  description = "Security groups permitted to reach the private EKS API endpoint."
  validation {
    condition     = length(var.security_group_ids) >= 1
    error_message = "At least one security group is required."
  }
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
