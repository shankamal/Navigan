#!/usr/bin/env bash
set -euo pipefail

CHART_VERSION="${NAVIGAN_MONITORING_CHART_VERSION:-89.2.4}"
NAMESPACE="${NAVIGAN_MONITORING_NAMESPACE:-navigan-monitoring}"
RELEASE="${NAVIGAN_MONITORING_RELEASE:-navigan-monitoring}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

command -v helm >/dev/null 2>&1 || {
  echo "Helm 3 is required." >&2
  exit 1
}
command -v kubectl >/dev/null 2>&1 || {
  echo "kubectl is required." >&2
  exit 1
}

SYSTEM_NODE_GROUP="${NAVIGAN_SYSTEM_NODE_GROUP:-navigan-system-v1}"
SYSTEM_NODES="$(
  kubectl get nodes \
    -l "navigan.io/platform-services=true,eks.amazonaws.com/nodegroup=$SYSTEM_NODE_GROUP" \
    --no-headers 2>/dev/null |
  wc -l |
  tr -d ' '
)"

if [ "$SYSTEM_NODES" -lt 2 ]; then
  echo "Monitoring requires at least two Ready Navigan system nodes." >&2
  exit 1
fi

NOT_READY="$(
  kubectl get nodes \
    -l "navigan.io/platform-services=true,eks.amazonaws.com/nodegroup=$SYSTEM_NODE_GROUP" \
    -o jsonpath='{range .items[*]}{range .status.conditions[?(@.type=="Ready")]}{.status}{"\n"}{end}{end}' |
  grep -vc '^True$' || true
)"

if [ "$NOT_READY" -ne 0 ]; then
  echo "All nodes in $SYSTEM_NODE_GROUP must be Ready before monitoring is installed." >&2
  exit 1
fi

helm upgrade --install "$RELEASE" \
  oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack \
  --version "$CHART_VERSION" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  --values "$SCRIPT_DIR/values.yaml" \
  --atomic \
  --timeout 15m \
  --wait

kubectl -n "$NAMESPACE" rollout status \
  deployment/navigan-monitoring-grafana \
  --timeout=5m

kubectl -n "$NAMESPACE" wait \
  --for=condition=Ready \
  prometheus/navigan-monitoring-prometheus \
  --timeout=10m

echo "Navigan monitoring is ready in namespace $NAMESPACE."
