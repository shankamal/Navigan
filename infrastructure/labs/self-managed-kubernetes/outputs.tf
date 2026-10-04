output "cluster_name" {
  value = local.name
}

output "vpc_id" {
  value = aws_vpc.lab.id
}

output "control_plane_instance_id" {
  value = aws_instance.control_plane.id
}

output "control_plane_private_ip" {
  value = aws_instance.control_plane.private_ip
}

output "worker_instance_ids" {
  value = aws_instance.worker[*].id
}

output "ssm_start_session_command" {
  value = "aws ssm start-session --target ${aws_instance.control_plane.id} --region ${var.aws_region}"
}

output "kubectl_command" {
  value = "sudo KUBECONFIG=/etc/kubernetes/admin.conf kubectl get nodes -o wide"
}

output "estimated_ec2_shape" {
  value = "1 x ${var.control_plane_instance_type} control plane, ${var.worker_count} x ${var.worker_instance_type} workers"
}

output "bootstrap_artifact_bucket" {
  value = aws_s3_bucket.artifacts.id
}

output "reference_application_validation_command" {
  value = "sudo KUBECONFIG=/etc/kubernetes/admin.conf kubectl logs -n retailflow job/retailflow-connectivity-check"
}
