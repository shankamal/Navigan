# Navigan cluster system repository template

Create one private repository from this template for every cluster:

```text
<customer-slug>-<cluster-slug>-system
```

Example:

```text
cus1-dev2-clus2-demo-system
```

This repository is the reviewed desired state for mandatory cluster utilities.
It contains no AWS credentials, Kubernetes tokens, connector tokens, Grafana
passwords, Git deploy keys, or other secret values.

## Bootstrap sequence

1. Terraform creates the EKS control plane and exactly one protected system
   node group.
2. The private, VPC-connected installer verifies at least two Ready system
   nodes.
3. The installer deploys the approved Argo CD chart and a read-only repository
   credential sourced from Secrets Manager.
4. The root Argo CD Application reconciles `applications/`.
5. Connector, Falco, monitoring and Headlamp report Healthy.
6. Navigan marks the platform baseline Ready and the cluster Active.

Application node groups are requested only after step 6.

## Promotion rules

- Every chart version is pinned in `catalog/approved-components.yaml`.
- Every referenced image must be mirrored into the approved customer OCI/ECR
  registry and scanned before promotion.
- Production uses a signed Git tag or immutable commit SHA.
- Pull requests require Platform Architecture and Security review through
  CODEOWNERS.
- Argo CD automated pruning is enabled only inside the `navigan-platform`
  project and approved namespaces.
- Secrets are resolved at runtime from the approved secret manager; they are
  never committed to Git.

`Kubernetes Dashboard` is intentionally not included because the upstream
project is archived and unmaintained. Navigan uses Headlamp as the supported
Kubernetes web UI.

