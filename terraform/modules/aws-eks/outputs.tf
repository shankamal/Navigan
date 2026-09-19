output "cluster_name" {
  value = aws_eks_cluster.this.name
}
output "cluster_arn" {
  value = aws_eks_cluster.this.arn
}
output "cluster_endpoint" {
  value     = aws_eks_cluster.this.endpoint
  sensitive = true
}
output "cluster_security_group_id" {
  value = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
}
output "managed_node_security_group_id" {
  value = aws_security_group.managed_nodes.id
}
output "node_groups" {
  value = merge(
    { for name, group in aws_eks_node_group.this : name => group.arn },
    { for name, group in data.aws_eks_node_group.adopted : name => group.arn },
  )
}
