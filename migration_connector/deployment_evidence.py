"""Bounded deployment metadata and owner-linked runtime image evidence."""

from .inventory import mapping, sequence, limited_text

LABELS = {
    "app.kubernetes.io/name",
    "app.kubernetes.io/instance",
    "app.kubernetes.io/version",
    "app.kubernetes.io/managed-by",
    "helm.sh/chart",
    "argocd.argoproj.io/instance",
    "kustomize.toolkit.fluxcd.io/name",
    "kustomize.toolkit.fluxcd.io/namespace",
    "helm.toolkit.fluxcd.io/name",
    "helm.toolkit.fluxcd.io/namespace",
}
ANNOTATIONS = {
    "meta.helm.sh/release-name",
    "meta.helm.sh/release-namespace",
    "argocd.argoproj.io/tracking-id",
}


FIELD_MANAGERS = {
    "kubectl", "kubectl-client-side-apply", "kubectl-create", "kubectl-set", "kubectl-patch", "kubectl-rollout",
    "helm", "argocd-controller", "argocd-application-controller",
    "helm-controller", "kustomize-controller", "tigera-operator",
}

def deployment_metadata(resource):
    metadata = mapping(resource.get("metadata"))
    return {
        "fieldManagers": sorted({item.get("manager") for item in sequence(metadata.get("managedFields")) if isinstance(item, dict) and item.get("manager") in FIELD_MANAGERS}),
        "labels": {
            k: limited_text(v, 253)
            for k, v in mapping(metadata.get("labels")).items()
            if k in LABELS and isinstance(v, str)
        },
        "annotations": {
            k: limited_text(v, 500)
            for k, v in mapping(metadata.get("annotations")).items()
            if k in ANNOTATIONS and isinstance(v, str)
        },
    }


def owner(resource):
    return next(
        (
            (v.get("kind"), v.get("name"))
            for v in sequence(mapping(resource.get("metadata")).get("ownerReferences"))
            if isinstance(v, dict) and v.get("controller") is True
        ),
        None,
    )


def collect_runtime(namespace, request, resources):
    """Only follow controller ownership. Never match Pods by name or image alone."""
    targets = {
        (r["kind"], r["name"]): r
        for r in resources
        if r.get("namespace") == namespace and r.get("pod") is not None
    }
    if not targets:
        return
    owners = {}
    unavailable = False
    for suffix in ("/apis/apps/v1/namespaces/{}/replicasets", "/apis/batch/v1/namespaces/{}/jobs"):
        try:
            payload = request(suffix.format(namespace))
            if mapping(payload.get("metadata")).get("continue"):
                unavailable = True
            for raw in sequence(payload.get("items"))[:2000]:
                if isinstance(raw, dict):
                    kind = "ReplicaSet" if suffix.endswith("replicasets") else "Job"
                    owners[(kind, mapping(raw.get("metadata")).get("name"))] = owner(raw)
        except RuntimeError:
            unavailable = True
    try:
        payload = request(f"/api/v1/namespaces/{namespace}/pods")
        pods = sequence(payload.get("items"))
        unavailable = (
            unavailable or bool(mapping(payload.get("metadata")).get("continue")) or len(pods) > 2000
        )
    except RuntimeError:
        for r in targets.values():
            r["runtimeEvidence"] = {"status": "UNAVAILABLE", "containers": []}
        return
    for r in targets.values():
        r["runtimeEvidence"] = {"status": "PARTIAL" if unavailable else "OBSERVED", "containers": []}
    for raw in pods[:2000]:
        if not isinstance(raw, dict) or mapping(raw.get("status")).get("phase") in {"Succeeded", "Failed"}:
            continue
        key = owner(raw)
        visited = set()
        keys = []
        while key and key not in visited:
            visited.add(key)
            if key in targets:
                keys.append(key)
            key = owners.get(key)
        for key in keys:
            evidence = targets[key]["runtimeEvidence"]
            for field, container_type in (
                ("containerStatuses", "APPLICATION"),
                ("initContainerStatuses", "INIT"),
            ):
                for status in sequence(mapping(raw.get("status")).get(field))[:100]:
                    status = mapping(status)
                    if len(evidence["containers"]) >= 500:
                        evidence["status"] = "PARTIAL"
                        break
                    evidence["containers"].append(
                        {
                            "name": limited_text(status.get("name"), 253),
                            "containerType": container_type,
                            "podName": limited_text(mapping(raw.get("metadata")).get("name"), 253),
                            "image": limited_text(status.get("image"), 1000),
                            "imageID": limited_text(status.get("imageID"), 1000),
                            "ready": status.get("ready") is True,
                        }
                    )
    for r in targets.values():
        evidence = r["runtimeEvidence"]
        evidence["containers"].sort(key=lambda c: (c["podName"] or "", c["containerType"], c["name"] or ""))
        if not evidence["containers"] and evidence["status"] == "OBSERVED":
            evidence["status"] = "NO_RUNNING_EVIDENCE"
