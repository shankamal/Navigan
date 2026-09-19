# Navigan monitoring baseline

This baseline installs Prometheus Operator, Prometheus, Grafana,
kube-state-metrics and node-exporter using the pinned
`kube-prometheus-stack` chart.

Prometheus, Grafana, the operator and kube-state-metrics are scheduled only on
nodes labelled:

```text
navigan.io/platform-services=true
eks.amazonaws.com/nodegroup=navigan-system-v1
```

They tolerate the protected system-node taint:

```text
navigan.io/system-only=true:NoSchedule
```

Node-exporter is intentionally a DaemonSet across all worker nodes so the
Dashboard can report node metrics.

## Security and exposure

- Grafana and Prometheus are internal `ClusterIP` services.
- No ingress or public load balancer is created.
- Grafana self-registration and telemetry are disabled.
- The generated Grafana administrator secret is not copied into source,
  configuration, or logs.
- Dashboard access must be provided through the Navigan identity-aware
  dashboard service, not by exposing Grafana directly.

## Current storage profile

The initial development profile is intentionally ephemeral. Prometheus retains
up to seven days or 8 GB while its pod remains running; Grafana dashboards and
datasources are provisioned from the chart. Before production promotion, add
encrypted persistent volumes using the environment's approved StorageClass and
backup policy.

## Install

Set the intended Kubernetes context, verify it points to the target cluster,
then run:

```bash
./platform/monitoring/install.sh
```

The approved chart version defaults to `89.2.4`. Override
`NAVIGAN_MONITORING_CHART_VERSION` only through the platform baseline promotion
process.

The approved default system node group is `navigan-system-v1`. A future
approved rename can be supplied to the installer with
`NAVIGAN_SYSTEM_NODE_GROUP`, together with a matching reviewed values file.

## Verify

```bash
kubectl -n navigan-monitoring get pods -o wide
kubectl -n navigan-monitoring get prometheus
kubectl -n navigan-monitoring get service
```

All server-side pods must be on Navigan system nodes. Node-exporter is expected
on every eligible worker node.
