# Cluster system GitOps architecture

## Decision

Each cluster receives a private system repository derived from
`platform/system-repo-template`. The repository name follows:

```text
<customer-slug>-<cluster-slug>-system
```

Argo CD runs in the cluster's protected system node group. This bootstrap Argo
CD instance owns only mandatory platform utilities in approved namespaces.
Customer application delivery can use a separate customer-level Argo CD control
plane later without coupling cluster readiness to application GitOps.

## Required components

| Component | Purpose | Placement |
|---|---|---|
| Navigan connector | Outbound inventory, health and RBAC reconciliation | System nodes |
| Argo CD | Reconciles the cluster system repository | System nodes |
| Prometheus Operator and Prometheus | Metrics and alert rules | System nodes |
| Grafana | Internal visualization service | System nodes |
| Falco | Runtime security sensor | DaemonSet on eligible nodes |
| Headlamp | Maintained Kubernetes web UI | System nodes |

Kubernetes Dashboard is excluded because it is archived and unmaintained.

## Supply-chain controls

Upstream Helm repositories are discovery sources, not production runtime
sources. A promotion workflow must:

1. Download the pinned chart.
2. Verify provenance/signatures where supplied.
3. Enumerate and mirror every image by digest into the approved OCI/ECR
   registry.
4. Scan charts and images against the approved severity policy.
5. Push the chart to the approved OCI registry.
6. Update the catalog through a reviewed pull request.
7. Sign the release commit or tag.

Argo CD is allowed to pull only from the private system Git repository and the
approved OCI registry.

## Readiness contract

The cluster remains `BOOTSTRAPPING` until all required catalog entries report:

- Argo CD Application `Synced`;
- Argo CD Application health `Healthy`;
- required replicas available;
- no blocking Falco/bootstrap security finding;
- connector heartbeat and inventory current.

A component failure moves the cluster to `BOOTSTRAP_FAILED`; it never silently
marks the cluster Active.
