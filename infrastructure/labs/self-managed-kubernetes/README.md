# Navigan self-managed Kubernetes migration lab

This module creates a disposable AWS lab for developing and validating the
Navigan migration accelerator.

## Topology

- One kubeadm control-plane EC2 instance.
- Two or more kubeadm worker EC2 instances across two Availability Zones.
- Ubuntu 24.04, containerd, Kubernetes and Calico.
- An isolated VPC with public egress for package and image downloads.
- Encrypted gp3 root volumes.
- AWS Systems Manager Session Manager access; inbound SSH is disabled by default.
- Automatic, short-lived kubeadm worker enrollment through an encrypted SSM
  parameter.
- A private, encrypted S3 bootstrap artifact used to deploy the reference
  application automatically.
- ingress-nginx, Metrics Server and the AWS EBS CSI driver.

The single control plane is intentional for this disposable development lab.
It is not a production high-availability design.

The default Mumbai topology uses one `t3.medium`, two `t3.small` workers and
30 GiB root volumes. Its September 2026 baseline is approximately USD 86 per
month before tax, internet data transfer and excess burst CPU charges. Stop the
instances whenever the lab is idle.

## Create a plan

```bash
cd infrastructure/labs/self-managed-kubernetes
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform validate
terraform plan -out migration-lab.tfplan
terraform show migration-lab.tfplan
```

Review the instance types, worker count, region and estimated AWS cost before
applying:

```bash
terraform apply migration-lab.tfplan
```

## Connect

Use the `ssm_start_session_command` Terraform output. On the control-plane node:

```bash
sudo KUBECONFIG=/etc/kubernetes/admin.conf kubectl get nodes -o wide
sudo KUBECONFIG=/etc/kubernetes/admin.conf kubectl get pods -A
```

## Verify the migration reference application

Terraform deploys the reference application automatically after every node and
required add-on becomes ready. It includes Deployments, StatefulSets,
DaemonSets, Services, Ingress, ConfigMaps, Secrets, EBS-backed claims, a Job,
a CronJob, HPA, PDB, RBAC, probes, scheduling constraints and NetworkPolicies.

Run the `reference_application_validation_command` output on the control-plane
node, then inspect all resources:

```bash
sudo KUBECONFIG=/etc/kubernetes/admin.conf kubectl get all,pvc,ingress,networkpolicy -n retailflow
```

RetailFlow is exposed through the existing ingress controller at
`https://retailflow.navigan.click:32024`.

## Remove the lab

Export any migration evidence first, then:

```bash
terraform destroy
```

The module deliberately does not create DNS records, certificates, a WAF, NAT
gateways, or a public Kubernetes API endpoint.
