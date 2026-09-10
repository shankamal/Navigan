variable "region" { type = string }
variable "provisioning_role_arn" { type = string }
variable "external_id" {
  type      = string
  sensitive = true
}
variable "cluster_name" { type = string }
variable "kubernetes_version" { type = string }
variable "endpoint_access" {
  type = string
  validation {
    condition     = contains(["PRIVATE", "PUBLIC_AND_PRIVATE"], var.endpoint_access)
    error_message = "endpoint_access must be PRIVATE or PUBLIC_AND_PRIVATE."
  }
}
variable "vpc_id" { type = string }
variable "cluster_subnet_ids" {
  type = list(string)
  validation {
    condition     = length(var.cluster_subnet_ids) >= 2
    error_message = "At least two cluster subnets are required."
  }
}
variable "node_subnet_ids" {
  type = list(string)
  validation {
    condition     = length(var.node_subnet_ids) >= 2
    error_message = "At least two node subnets are required."
  }
}
variable "cluster_security_group_ids" { type = list(string) }
variable "node_security_group_ids" { type = list(string) }
variable "cluster_role_arn" { type = string }
variable "node_role_arn" { type = string }
variable "node_volume_kms_key_arn" { type = string }
variable "cluster_secrets_kms_key_arn" {
  type     = string
  default  = null
  nullable = true
}
variable "node_groups" {
  type = list(object({
    name          = string
    instanceTypes = list(string)
    capacityType  = string
    desiredSize   = number
    minSize       = number
    maxSize       = number
    diskSizeGiB   = number
  }))
}
variable "tags" { type = map(string) }
