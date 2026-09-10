variable "region" { type = string }
variable "navigan_execution_role_arn" { type = string }
variable "external_id" {
  type      = string
  sensitive = true
}
variable "eks_cluster_role_arns" { type = set(string) }
variable "eks_node_role_arns" { type = set(string) }
variable "kms_key_arns" { type = set(string) }
variable "permissions_boundary_arn" {
  type    = string
  default = null
}
