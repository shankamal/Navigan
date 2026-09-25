# Navigan cluster connector

The connector is outbound-only and runs on any conformant Kubernetes
distribution. It does not use a cloud-provider API. Its service account reads
cluster inventory, reconciles approved Kubernetes RBAC assignments, and may
patch only its own namespaced Deployment when Navigan publishes a newer OCI
image.

Do not put the token in Helm values, Git, container images, ConfigMaps, logs, or
shell history. Create the Secret interactively or through the customer's
approved secret-management workflow.

The connector reports namespace inventory and reconciles the desired Kubernetes
access state through:

`POST {ApiBaseUrl}/connectors/{connectorId}/inventory/namespaces`

`GET {ApiBaseUrl}/connectors/{connectorId}/access/desired`

`POST {ApiBaseUrl}/connectors/{connectorId}/access/status`

Its service account can read namespace names and manage only the Kubernetes
RBAC resources labeled as Navigan-managed assignments. Runtime update access is
restricted by `resourceNames` to the `navigan-cluster-connector` Deployment.

## Portable installation and recovery

The same Helm chart is used for EKS, AKS, GKE, OKE, OpenShift, and self-managed
Kubernetes. The only prerequisite is a kubeconfig with access to the target
cluster and permission to install the chart.

An existing connector release can be bootstrapped or recovered without any
cloud-specific command:

```bash
helm upgrade navigan-cluster-connector ./connector/helm \
  --namespace navigan-system \
  --reuse-values \
  --set-string image.repository=REGISTRY/REPOSITORY \
  --set-string image.digest=sha256:IMAGE_DIGEST \
  --wait
```

If the registry needs Kubernetes pull credentials, configure
`image.pullSecrets` with an existing Secret. Once a connector with runtime
management support is online, later image updates are requested through the
normal desired-state poll. Access reconciliation is completed before an update
is attempted, so image or chart problems do not leave grants awaiting sync.
