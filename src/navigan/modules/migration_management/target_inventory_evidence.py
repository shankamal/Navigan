"""Conservative capability evidence from existing read-only target runtime inventory.

No Kubernetes API calls, deployments, credentials, or mutations.
"""

def build_target_inventory_evidence(resources, metrics):
    resources = [r for r in (resources or []) if isinstance(r, dict)]
    metrics = metrics if isinstance(metrics, dict) else {}
    nodes = [r for r in resources if r.get("kind") == "Node"]
    capacity = []
    for node in nodes:
        cpu, memory = node.get("allocatableCpu"), node.get("allocatableMemory")
        if cpu is None or memory is None or cpu == "" or memory == "":
            continue
        capacity.append({
            "name": node.get("name"), "allocatableCpu": cpu,
            "allocatableMemory": memory, "unschedulable": node.get("unschedulable"),
            "taintCount": node.get("taintCount"), "nodeLabels": node.get("nodeLabels"),
            "nodeTaints": node.get("nodeTaints"),
        })
    api_versions = [
        version for metric, version in (
            ("apiDiscoveryCoreV1", "v1"), ("apiDiscoveryAppsV1", "apps/v1"))
        if metrics.get(metric) == 1
    ]
    api_resources = [
        {"apiVersion": version, "kind": kind}
        for group, version, kinds in (
            ("coreV1", "v1", ("Pod", "Service", "PersistentVolumeClaim", "ConfigMap", "Secret", "ServiceAccount")),
            ("appsV1", "apps/v1", ("Deployment", "StatefulSet", "DaemonSet")),
        )
        for kind in kinds if metrics.get(f"apiKind_{group}_{kind}") == 1
    ]
    states = lambda pairs: {
        kind: ("AVAILABLE" if metrics.get(metric) == 1 else
               "PERMISSION_DENIED" if metrics.get(metric) == 2 else
               "UNAVAILABLE" if metrics.get(metric) == 3 else "NOT_REPORTED")
        for kind, metric in pairs
    }
    storage = states((("StorageClass", "storageClassDiscoveryStatus"),
                      ("CSIDriver", "csiDriverDiscoveryStatus")))
    supplementary = states(tuple(
        (kind, f"discoveryStatus_{kind}") for kind in (
            "Ingress", "NetworkPolicy", "ServiceAccount", "Role", "RoleBinding",
            "ClusterRole", "ClusterRoleBinding", "CustomResourceDefinition")))
    kinds = {}
    for r in resources:
        if isinstance(r.get("kind"), str) and r["kind"].strip():
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    return {
        "nodeCapacity": capacity,
        "nodeCapacityCoverage": {
            "observedNodes": len(nodes), "nodesWithCapacity": len(capacity),
            "missingNodes": len(nodes) - len(capacity),
        },
        "discoveredApiVersions": api_versions,
        "discoveredApiResources": api_resources,
        "storageDiscovery": storage,
        "supplementaryDiscovery": supplementary,
        "collectionGaps": {
            "nodeCapacity": "MISSING" if len(capacity) < len(nodes) or not nodes else "PARTIAL",
            "kubernetesApi": "MISSING" if not api_versions else "PARTIAL",
            "storage": "MISSING" if any(value != "AVAILABLE" for value in storage.values()) else "PARTIAL",
            "networking": "MISSING" if any(supplementary[key] != "AVAILABLE" for key in ("Ingress", "NetworkPolicy")) else "PARTIAL",
            "identity": "MISSING" if any(supplementary[key] != "AVAILABLE" for key in ("ServiceAccount", "Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding")) else "PARTIAL",
            "operators": "MISSING" if supplementary["CustomResourceDefinition"] != "AVAILABLE" else "PARTIAL",
        },
        "collectionLimitations": {
            "nodeCapacity": "No allocatable CPU/memory was reported for every observed node; never treat missing values as zero.",
            "kubernetesApi": "API discovery metrics absent is not evidence that the target does not support Kubernetes APIs.",
            "storage": "Discovery flags establish collection status, not provisioning or PVC compatibility.",
            "networking": "Service objects do not prove DNS, ingress, routing or NetworkPolicy compatibility.",
            "identity": "RBAC object observations do not verify effective permissions or workload identity.",
            "operators": "CRD observations do not establish operator readiness or admission compatibility.",
        },
    }
